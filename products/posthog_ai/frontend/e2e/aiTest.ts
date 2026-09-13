import { mockFeatureFlags } from '@playwright-utils/mockApi'
import { APIRequestContext, Page, test as base, expect } from '@playwright/test'

import flags from './flags.json'

declare global {
    interface Window {
        aiE2eStreams: Set<AbortController>
    }
}

export type Provider = 'claude' | 'codex'
type Fault = 'registration' | 'worker' | 'approval' | 'approval_confirmation' | 'model'

export interface ResponseStep {
    provider: Provider
    model: string
    fixture: 'text' | 'insight-update' | 'tool-search'
    user_message: string
    tool_result?: { call_id: string; contains: string }
    history_contains?: string[]
    substitutions: Record<string, string>
}

export interface Seed {
    id: string
    provider: Provider
    model: string
    team_id: number
    email: string
    password: string
    insight_id: number
    connection_id: string
    task_id: string | null
    run_id: string | null
}

interface Snapshot {
    task_id: string | null
    run_id: string | null
    insight_name: string
    task_count: number
    run_count: number
    tool_executions: number
    runs: { status: string; state: Record<string, unknown> }[]
    consumed: { step: number }[]
    timeline: { fault: Fault; event: string; status?: number; request_id?: string; run_id?: string }[]
}

export class AiAttempt {
    constructor(
        private request: APIRequestContext,
        public seed: Seed
    ) {}

    async control<T = unknown>(operation: string, data: unknown = {}): Promise<T> {
        return controllerRequest<T>(this.request, `${this.seed.id}/${operation}`, data)
    }

    async configure(steps: ResponseStep[]): Promise<void> {
        await this.control('configure', { steps })
    }

    fault(name: Fault): {
        arm: (target?: string) => Promise<unknown>
        waitUntilReached: () => Promise<unknown>
        release: () => Promise<unknown>
        reset: () => Promise<unknown>
    } {
        return {
            arm: (target) => this.control(`fault/${name}/arm`, target === undefined ? {} : { target }),
            waitUntilReached: () => this.control(`fault/${name}/waitUntilReached`),
            release: () => this.control(`fault/${name}/release`),
            reset: () => this.control(`fault/${name}/reset`),
        }
    }

    async open(page: Page, options: { warm?: boolean; path?: string } = {}): Promise<void> {
        this.seed = await this.control<Seed>('start', options)
        const login = await page.request.post('/api/login/', {
            data: { email: this.seed.email, password: this.seed.password },
        })
        expect(login.ok(), await login.text()).toBeTruthy()
        await mockFeatureFlags(
            page,
            Object.fromEntries(
                Object.entries(flags)
                    .filter(([, flag]) => flag.consumers.includes('browser'))
                    .map(([key, flag]) => [key, flag.value])
            )
        )
        // The controller seeds the exact warm target; speculative UI warming would create unrelated runs.
        await page.route(/\/tasks\/(?:[^/]+\/)?warm\/$/, (route) => route.fulfill({ json: {} }))
        await page.goto(options.path ?? `/project/${this.seed.team_id}/tasks/new`)
        if (!options.path) {
            await expect(page.getByTestId('task-composer-input')).toBeVisible()
        }
    }

    async warmResume(): Promise<void> {
        this.seed = await this.control<Seed>('warm_resume')
    }

    async snapshot(): Promise<Snapshot> {
        return this.control<Snapshot>('snapshot')
    }

    async reconnectStream(page: Page): Promise<void> {
        const reconnected = page.waitForResponse(
            (response) =>
                response.url().startsWith(`${process.env.AI_E2E_PROXY_URL}/v1/runs/${this.seed.run_id}/stream`) &&
                response.status() === 200 &&
                Boolean(response.request().headers()['last-event-id'])
        )
        await page.evaluate(() => {
            if (window.aiE2eStreams.size === 0) {
                throw new Error('No active agent-proxy stream to disconnect')
            }
            for (const stream of window.aiE2eStreams) {
                stream.abort()
            }
        })
        await reconnected
    }

    text(userMessage: string, text: string, step: number): ResponseStep {
        return {
            provider: this.seed.provider,
            model: this.seed.model,
            fixture: 'text',
            user_message: userMessage,
            substitutions: { model: this.seed.model, message_id: `msg_${this.seed.id}_${step}`, text },
        }
    }

    discover(message: string): ResponseStep {
        return {
            ...this.text(message, '', 0),
            fixture: this.seed.provider === 'claude' ? 'insight-update' : 'tool-search',
            substitutions: {
                model: this.seed.model,
                message_id: `msg_${this.seed.id}_0`,
                tool_call_id: `discovery_${this.seed.id}`,
                tool_name: this.seed.provider === 'claude' ? 'ToolSearch' : 'mcp__posthog__exec',
                text: 'posthog exec',
                arguments: JSON.stringify({ query: 'select:mcp__posthog__exec', max_results: 1 }),
            },
        }
    }

    exec(message: string, command: string, step: number, previous: ResponseStep['tool_result']): ResponseStep {
        return {
            ...this.text(message, '', step),
            fixture: 'insight-update',
            tool_result: previous,
            substitutions: {
                model: this.seed.model,
                message_id: `msg_${this.seed.id}_${step}`,
                tool_call_id: `call_${this.seed.id}_${step}`,
                tool_name: this.seed.provider === 'claude' ? 'mcp__posthog__exec' : 'exec',
                ...(this.seed.provider === 'codex' ? { tool_namespace: 'mcp__posthog' } : {}),
                arguments: JSON.stringify({ command }),
            },
        }
    }
}

export async function controllerRequest<T>(request: APIRequestContext, path: string, data: unknown): Promise<T> {
    if (!process.env.AI_E2E_CONTROLLER || !process.env.AI_E2E_TOKEN) {
        throw new Error('Run through hogli test:e2e:ai so services and fault controls are installed')
    }
    const response = await request.post(`${process.env.AI_E2E_CONTROLLER}/control/${path}`, {
        headers: { Authorization: `Bearer ${process.env.AI_E2E_TOKEN}` },
        data,
        timeout: 120_000,
    })
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
}

export const test = base.extend<{ ai: AiAttempt; provider: Provider }>({
    provider: ['claude', { option: true }],
    ai: async ({ request, provider, page }, provide, testInfo) => {
        const browserLog: string[] = []
        const streams: { url: string; status: number; resumed: boolean }[] = []
        const djangoStreams: string[] = []
        const proxyUrl = process.env.AI_E2E_PROXY_URL
        if (!proxyUrl) {
            throw new Error('The AI runner must supply its agent-proxy URL')
        }
        await page.addInitScript((proxyUrl) => {
            window.aiE2eStreams = new Set()
            const fetch = window.fetch.bind(window)
            window.fetch = async (input, init) => {
                const request = new Request(input, init)
                if (!request.url.startsWith(`${proxyUrl}/v1/runs/`) || !request.url.includes('/stream')) {
                    return fetch(input, init)
                }
                const transport = new AbortController()
                window.aiE2eStreams.add(transport)
                const signal = AbortSignal.any([request.signal, transport.signal])
                signal.addEventListener('abort', () => window.aiE2eStreams.delete(transport), { once: true })
                return fetch(request, { signal })
            }
        }, proxyUrl)
        page.on('request', (request) => {
            const url = new URL(request.url())
            if (url.pathname.includes('/runs/') && url.pathname.endsWith('/stream/')) {
                djangoStreams.push(url.pathname)
            }
        })
        page.on('response', (response) => {
            if (response.url().startsWith(`${proxyUrl}/v1/runs/`) && response.url().includes('/stream')) {
                streams.push({
                    url: new URL(response.url()).pathname,
                    status: response.status(),
                    resumed: Boolean(response.request().headers()['last-event-id']),
                })
            }
        })
        page.on('console', (message) => {
            browserLog.push(`${message.type()}: ${message.text()}`)
        })
        page.on('pageerror', (error) => browserLog.push(`pageerror: ${error.stack}`))
        const seed = await controllerRequest<Seed>(request, 'attempt', { provider })
        const attempt = new AiAttempt(request, seed)
        try {
            await provide(attempt)
            expect(djangoStreams, 'The production profile must not fall back to Django SSE').toEqual([])
            expect(
                streams.some((stream) => stream.status === 200),
                'Expected a real agent-proxy stream'
            ).toBeTruthy()
        } finally {
            await testInfo.attach('proxy-streams', { body: JSON.stringify(streams), contentType: 'application/json' })
            await testInfo.attach('browser-console', { body: browserLog.join('\n'), contentType: 'text/plain' })
            try {
                await testInfo.attach('controller', {
                    body: JSON.stringify(await attempt.snapshot(), null, 2),
                    contentType: 'application/json',
                })
            } finally {
                await attempt.control('finish')
            }
        }
    },
})

export async function send(page: Page, message: string): Promise<void> {
    await page.getByTestId(/^(task|sandbox)-composer-input$/).fill(message)
    await page.getByTestId(/^(task|sandbox)-composer-send$/).click()
}
