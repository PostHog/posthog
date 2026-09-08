import { mockFeatureFlags } from '@playwright-utils/mockApi'
import { APIRequestContext, Page, test as base, expect } from '@playwright/test'

export type Provider = 'claude' | 'codex'
type Fault = 'registration' | 'worker' | 'approval'

export interface ResponseStep {
    provider: Provider
    model: string
    fixture: 'text' | 'insight-update' | 'tool-search'
    user_message: string
    tool_result?: { call_id: string; contains: string }
    substitutions: Record<string, string>
}

interface Seed {
    id: string
    provider: Provider
    model: string
    team_id: number
    email: string
    password: string
    insight_id: number
    connection_id: string
    task_id: string
    run_id: string
}

interface Snapshot {
    insight_name: string
    task_count: number
    run_count: number
    tool_executions: number
    timeline: { fault: Fault; event: string; status?: number; request_id?: string }[]
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
        arm: () => Promise<unknown>
        waitUntilReached: () => Promise<unknown>
        release: () => Promise<unknown>
        reset: () => Promise<unknown>
    } {
        return {
            arm: () => this.control(`fault/${name}/arm`),
            waitUntilReached: () => this.control(`fault/${name}/waitUntilReached`),
            release: () => this.control(`fault/${name}/release`),
            reset: () => this.control(`fault/${name}/reset`),
        }
    }

    async open(page: Page): Promise<void> {
        this.seed = await this.control<Seed>('start')
        const login = await page.request.post('/api/login/', {
            data: { email: this.seed.email, password: this.seed.password },
        })
        expect(login.ok(), await login.text()).toBeTruthy()
        await mockFeatureFlags(page, { tasks: true, 'tasks-stream-via-proxy': false })
        await page.goto(`/project/${this.seed.team_id}/tasks/new`)
        await expect(page.getByTestId('task-composer-input')).toBeVisible()
    }

    async snapshot(): Promise<Snapshot> {
        return this.control<Snapshot>('snapshot')
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
}

async function controllerRequest<T>(request: APIRequestContext, path: string, data: unknown): Promise<T> {
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
        page.on('console', (message) => {
            browserLog.push(`${message.type()}: ${message.text()}`)
        })
        page.on('pageerror', (error) => browserLog.push(`pageerror: ${error.stack}`))
        const seed = await controllerRequest<Seed>(request, 'attempt', { provider })
        const attempt = new AiAttempt(request, seed)
        try {
            await provide(attempt)
        } finally {
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
