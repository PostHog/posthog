import { mockFeatureFlags } from '@playwright-utils/mockApi'
import { expect, test as base } from '@playwright-utils/workspace-test-base'
import { Page, Route } from '@playwright/test'

import { controllerRequest, Seed } from './aiTest'

export const TASK_ID = '0190a000-0000-4000-8000-0000000000a1'
export const RUN_ID = '0190a000-0000-4000-8000-0000000000b2'
export const NEXT_RUN_ID = '0190a000-0000-4000-8000-0000000000c3'
export type Frame = Record<string, unknown>

type StreamWindow = typeof window & {
    aiStreams: Map<string, ReadableStreamDefaultController<Uint8Array>>
    aiStreamConnections: Record<string, number>
}

export function notification(method: string, params: Record<string, unknown> = {}, runId = RUN_ID): Frame {
    return { type: 'notification', source_run_id: runId, notification: { method, params } }
}

export function message(text: string, role: 'user' | 'agent' = 'agent', runId = RUN_ID): Frame {
    return notification(
        'session/update',
        {
            update: {
                sessionUpdate: role === 'user' ? 'user_message_chunk' : 'agent_message',
                messageId: `synthetic-${runId}-${role}-${text}`,
                content: { type: 'text', text },
            },
        },
        runId
    )
}

export function ready(runId = RUN_ID): Frame {
    return notification('_posthog/progress', { group: `setup:${runId}`, step: 'agent', status: 'completed' }, runId)
}

export function approval(
    kind: 'permission' | 'question' | 'plan' = 'permission',
    requestId = 'approval-1',
    runId = RUN_ID
): Frame {
    const names = { permission: 'mcp__synthetic__write', question: 'AskUserQuestion', plan: '' }
    const questions = [
        {
            question: 'Which synthetic environment?',
            header: 'Environment',
            multiSelect: true,
            options: [
                { label: 'Example', description: 'Use the example environment' },
                { label: 'Preview', description: 'Use the preview environment' },
            ],
        },
    ]
    return notification(
        '_posthog/permission_request',
        {
            requestId,
            toolCall: {
                toolCallId: `tool-${requestId}`,
                toolName: names[kind],
                title: names[kind],
                _meta: {
                    claudeCode: { toolName: names[kind] },
                    ...(kind === 'question' ? { codeToolKind: 'question', questions } : {}),
                },
                rawInput:
                    kind === 'question'
                        ? { questions }
                        : kind === 'plan'
                          ? { toolName: 'ExitPlanMode', plan: 'Use the synthetic environment and report the result.' }
                          : {},
            },
            options:
                kind === 'question'
                    ? questions[0].options.map((option, index) => ({
                          optionId: `option_${index}`,
                          name: option.label,
                          kind: 'allow_once',
                      }))
                    : [
                          { optionId: kind === 'plan' ? 'auto' : 'allow_once', name: 'Allow', kind: 'allow_once' },
                          { optionId: 'reject', name: 'Do it differently', kind: 'reject_with_feedback' },
                      ],
        },
        runId
    )
}

export class PendingCommand {
    constructor(
        public body: { method: string; params?: Record<string, unknown> },
        public runId: string,
        private route: Route,
        private release: () => void
    ) {}

    async respond(body?: unknown, status = 200): Promise<void> {
        const result =
            this.body.method === 'user_message'
                ? { queued: true }
                : this.body.method === 'cancel'
                  ? { cancelled: true }
                  : { resolved: true }
        await this.route.fulfill({ status, json: body ?? { jsonrpc: '2.0', result } })
        this.release()
    }
}

export class RunSurfaceHarness {
    status = 'in_progress'
    runId = RUN_ID
    history: Frame[] = [
        notification('_posthog/run_started', { runId: RUN_ID }),
        ready(),
        message('A synthetic task', 'user'),
        message('Working on the synthetic task.'),
    ]
    commands: PendingCommand[] = []

    constructor(
        public page: Page,
        public teamId: string
    ) {}

    run(id = this.runId): Record<string, unknown> {
        return {
            id,
            task: TASK_ID,
            status: this.status,
            environment: 'cloud',
            runtime_adapter: 'claude',
            model: 'claude-sonnet-4-6',
            reasoning_effort: 'medium',
            state: {
                initial_permission_mode: 'auto',
                runtime_adapter: 'claude',
                model: 'claude-sonnet-4-6',
                reasoning_effort: 'medium',
            },
            artifacts: [],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            completed_at: this.status === 'completed' ? new Date().toISOString() : null,
        }
    }

    task(): Record<string, unknown> {
        return {
            id: TASK_ID,
            task_number: 1,
            slug: 'synthetic-run',
            title: 'Synthetic conversation',
            description: '',
            origin_product: 'posthog_ai',
            runtime: 'acp',
            repository: null,
            github_integration: null,
            internal: false,
            latest_run: this.run(),
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            created_by: {
                id: 1,
                uuid: 'synthetic-user',
                distinct_id: 'synthetic-user',
                first_name: 'Synthetic',
                email: 'tester@example.com',
            },
        }
    }

    async install(): Promise<void> {
        await this.page.clock.install()
        await this.page.route(/\/event_definitions\/?(?:\?|$)/, (route) =>
            route.fulfill({
                json: { count: 1, next: null, results: [{ id: TASK_ID, name: 'synthetic_retry_event' }] },
            })
        )
        await mockFeatureFlags(this.page, { tasks: true, 'tasks-stream-via-proxy': false, 'phai-sandbox-mode': true })
        await this.page.addInitScript(() => {
            const target = window as StreamWindow
            target.aiStreams = new Map()
            target.aiStreamConnections = {}
            const original = window.fetch.bind(window)
            window.fetch = (input, init) => {
                const url = new URL(input instanceof Request ? input.url : String(input), location.href)
                const match = url.pathname.match(/\/runs\/([^/]+)\/stream\/?$/)
                if (!match) {
                    return original(input, init)
                }
                const stream = new ReadableStream<Uint8Array>({
                    start(controller) {
                        target.aiStreams.set(match[1], controller)
                        target.aiStreamConnections[match[1]] = (target.aiStreamConnections[match[1]] ?? 0) + 1
                        const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined)
                        signal?.addEventListener(
                            'abort',
                            () => {
                                if (target.aiStreams.get(match[1]) === controller) {
                                    target.aiStreams.delete(match[1])
                                    controller.close()
                                }
                            },
                            { once: true }
                        )
                    },
                })
                return Promise.resolve(new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } }))
            }
        })
        await this.page.route(/\/api\/(environments|projects)\/[^/]+\/tasks\//, async (route) => {
            const path = new URL(route.request().url()).pathname
            const command = path.match(/\/runs\/([^/]+)\/command\/$/)
            if (command) {
                await new Promise<void>((resolve) => {
                    this.commands.push(new PendingCommand(route.request().postDataJSON(), command[1], route, resolve))
                })
            } else if (path.endsWith('/logs/')) {
                await route.fulfill({
                    contentType: 'application/jsonl',
                    body: this.history.map((frame) => JSON.stringify(frame)).join('\n'),
                })
            } else if (path.endsWith('/stream_token/')) {
                await route.fulfill({ json: { token: 'synthetic-token', stream_base_url: null } })
            } else if (path.endsWith('/warm/') || path.endsWith('/cancel/')) {
                await route.fulfill({ json: {} })
            } else if (path.endsWith('/runs/')) {
                await route.fulfill({ json: { results: [this.run()], count: 1, next: null } })
            } else if (/\/runs\/[^/]+\/$/.test(path)) {
                await route.fulfill({ json: this.run(path.split('/').at(-2)) })
            } else if (path.endsWith(`/tasks/${TASK_ID}/`)) {
                await route.fulfill({ json: this.task() })
            } else if (path.endsWith('/tasks/')) {
                await route.fulfill({ json: { results: [this.task()], count: 1, next: null } })
            } else {
                await route.fallback()
            }
        })
    }

    async open(): Promise<void> {
        await this.page.goto(`/project/${this.teamId}/tasks/${TASK_ID}`)
        await expect(this.page.getByText('Working on the synthetic task.', { exact: true })).toBeVisible()
        await this.connected()
    }

    async holdCreation(): Promise<{ request: Promise<PendingCommand> }> {
        let capture!: (command: PendingCommand) => void
        const request = new Promise<PendingCommand>((resolve) => {
            capture = resolve
        })
        await this.page.route(
            (url) => url.pathname.endsWith('/tasks/'),
            async (route) => {
                if (route.request().method() !== 'POST') {
                    await route.fallback()
                    return
                }
                await new Promise<void>((release) =>
                    capture(new PendingCommand(route.request().postDataJSON(), this.runId, route, release))
                )
            }
        )
        return { request }
    }

    async openSidebar(): Promise<void> {
        const csrf = (await this.page.context().cookies()).find((cookie) => cookie.name === 'posthog_csrftoken')
        const intro = await this.page.request.patch('/api/users/@me/product_intro_seen/', {
            headers: { 'X-CSRFToken': csrf?.value ?? '' },
            data: { product_key: 'posthog_ai_onboarding', seen: true },
        })
        expect(intro.ok()).toBeTruthy()
        await this.page.route('**/api/billing/usage/team_options/', (route) =>
            route.fulfill({ json: { team_id_options: [] } })
        )
        await this.page.route(/\/api\/billing\/(usage|spend)\/\?/, (route) =>
            route.fulfill({ json: { status: 'ok', type: 'timeseries', customer_id: 'synthetic', results: [] } })
        )
        await this.page.goto(`/project/${this.teamId}/insights/new#panel=max`)
        await expect(this.page.getByTestId('task-composer-input')).toBeVisible()
    }

    async connected(): Promise<void> {
        await expect
            .poll(() => this.page.evaluate((runId) => (window as StreamWindow).aiStreams.has(runId), this.runId))
            .toBe(true)
    }

    async reconnect(): Promise<void> {
        const previous = await this.page.evaluate((runId) => {
            const target = window as StreamWindow
            const controller = target.aiStreams.get(runId)
            if (!controller) {
                throw new Error(`No stream for ${runId}`)
            }
            target.aiStreams.delete(runId)
            controller.close()
            return target.aiStreamConnections[runId]
        }, this.runId)
        await expect
            .poll(() => this.page.evaluate((runId) => (window as StreamWindow).aiStreamConnections[runId], this.runId))
            .toBeGreaterThan(previous)
        await this.connected()
    }

    async emit(...frames: Frame[]): Promise<void> {
        this.history.push(...frames)
        await this.page.evaluate(
            ({ frames, runId }) => {
                const controller = (window as StreamWindow).aiStreams.get(runId)
                if (!controller) {
                    throw new Error(`No stream for ${runId}`)
                }
                for (const frame of frames) {
                    controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(frame)}\n\n`))
                }
            },
            { frames, runId: this.runId }
        )
    }

    async command(index = this.commands.length): Promise<PendingCommand> {
        await expect
            .poll(() => this.commands.length, { message: `Waiting for command ${index + 1}` })
            .toBeGreaterThan(index)
        return this.commands[index]
    }

    async queue(text: string): Promise<void> {
        await this.page.getByTestId('sandbox-composer-input').fill(text)
        // Settle the draft debounce; the fast-submit case exercises sending before it finishes.
        await this.page.clock.runFor(150)
        await this.page.getByTestId('sandbox-composer-send').click()
        await expect(this.page.getByText('Up next', { exact: true })).toBeVisible()
        await expect(this.page.getByTestId('sandbox-composer-input')).toHaveValue('')
    }
}

export const test = base.extend<{ surface: RunSurfaceHarness }>({
    surface: async ({ page, playwrightSetup }, provide) => {
        if (process.env.AI_E2E_CONTROLLER) {
            const seed = await controllerRequest<Seed>(page.request, 'attempt', { provider: 'claude', surface: true })
            try {
                const login = await page.request.post('/api/login/', {
                    data: { email: seed.email, password: seed.password },
                })
                expect(login.ok()).toBeTruthy()
                const surface = new RunSurfaceHarness(page, String(seed.team_id))
                await surface.install()
                await provide(surface)
            } finally {
                await page.unrouteAll({ behavior: 'ignoreErrors' })
                await controllerRequest(page.request, `${seed.id}/finish`, {})
            }
            return
        }
        const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        await playwrightSetup.login(page, workspace)
        const surface = new RunSurfaceHarness(page, workspace.team_id)
        await surface.install()
        await provide(surface)
        await page.unrouteAll({ behavior: 'ignoreErrors' })
    },
})

export { expect }
