import { ApiError, setAuthProvider } from '@/api/client'

import type { Clock } from './clock'
import { handoffErrorMessage, kickOffReportTask } from './kickoff'

interface Call {
    url: string
    method: string
    headers: Record<string, string>
    body: unknown
}

type Reply = { status: number; body: unknown }

const calls: Call[] = []
let replies: Reply[] = []

function fakeResponse({ status, body }: Reply): Response {
    return {
        ok: status >= 200 && status < 300,
        status,
        headers: { get: () => null },
        text: async () => JSON.stringify(body),
    } as unknown as Response
}

function fakeClock(): Clock & { delays: number[] } {
    let now = 0
    const delays: number[] = []
    return {
        delays,
        now: () => now,
        sleep: async (ms) => {
            delays.push(ms)
            now += ms
        },
    }
}

const REPORT = { status: 200, body: { id: 'rep-1', title: 'Legend crash', summary: 'TypeError in ChartLegend' } }
const RUN = {
    id: 'run-1',
    task: 'task-1',
    status: 'queued',
    stage: null,
    branch: null,
    error_message: null,
    output: null,
    completed_at: null,
}
const RUN_FIELDS = {
    runtime_adapter: 'codex',
    model: 'gpt-5.5',
    reasoning_effort: 'xhigh',
    initial_permission_mode: 'plan',
    branch: 'release',
} as const
const WARM_UNAVAILABLE = (token: string): Reply => ({
    status: 503,
    body: { code: 'warm_run_activation_unavailable', retry_token: token },
})

describe('kickoff', () => {
    beforeEach(() => {
        calls.length = 0
        replies = []
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        globalThis.fetch = jest.fn(async (url: string, init: RequestInit) => {
            calls.push({
                url,
                method: init.method ?? 'GET',
                headers: init.headers as Record<string, string>,
                body: init.body ? JSON.parse(String(init.body)) : undefined,
            })
            const reply = replies.shift()
            if (!reply) {
                throw new Error(`Unexpected request to ${url}`)
            }
            return fakeResponse(reply)
        }) as unknown as typeof fetch
    })

    afterEach(() => {
        setAuthProvider(null)
    })

    test('a task created with its run is not started a second time', async () => {
        replies = [
            REPORT,
            { status: 201, body: { id: 'task-1', title: 'Legend crash', signal_report: 'rep-1', latest_run: RUN } },
        ]
        await expect(kickOffReportTask('rep-1', { run: RUN_FIELDS, clock: fakeClock() })).resolves.toEqual({
            taskId: 'task-1',
            runId: 'run-1',
        })
        expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
            'GET https://app.example.com/api/projects/2/signals/reports/rep-1/',
            'POST https://app.example.com/api/projects/2/tasks/',
        ])
        // Exact, so a stray `repository` (the server rejects it) or a run option on the task body fails.
        expect(calls[1]?.body).toEqual({
            title: 'Legend crash',
            description: expect.stringContaining('Report summary:\nTypeError in ChartLegend'),
            origin_product: 'signal_report',
            signal_report: 'rep-1',
            signal_report_task_relationship: 'implementation',
        })
    })

    test('a task created without a run gets an interactive run with the prompt and the picked options', async () => {
        replies = [
            REPORT,
            { status: 201, body: { id: 'task-1', title: 'Legend crash', signal_report: 'rep-1', latest_run: null } },
            { status: 200, body: { id: 'task-1', latest_run: null, run: RUN } },
        ]
        await expect(kickOffReportTask('rep-1', { run: RUN_FIELDS, clock: fakeClock() })).resolves.toEqual({
            taskId: 'task-1',
            runId: 'run-1',
        })
        expect(`${calls[2]?.method} ${calls[2]?.url}`).toBe(
            'POST https://app.example.com/api/projects/2/tasks/task-1/run/'
        )
        expect(calls[2]?.body).toEqual({
            run_source: 'signal_report',
            signal_report_id: 'rep-1',
            mode: 'interactive',
            pending_user_message: (calls[1]?.body as { description: string }).description,
            ...RUN_FIELDS,
        })
    })

    test.each([400, 429, 503, 500])('retries the original task after run refusal %s', async (status) => {
        const created = { id: 'task-1', title: 'Legend crash', signal_report: 'rep-1', latest_run: null }
        replies = [REPORT, { status: 201, body: created }, { status, body: { error: 'Run unavailable' } }]
        let taskId: string | undefined
        const onTaskCreated = (id: string): void => {
            taskId = id
        }
        await expect(kickOffReportTask('rep-1', { run: RUN_FIELDS, onTaskCreated })).rejects.toMatchObject({ status })
        expect(taskId).toBe('task-1')
        replies = [REPORT, { status: 200, body: created }, { status: 200, body: { ...created, run: RUN } }]
        await expect(kickOffReportTask('rep-1', { run: RUN_FIELDS, taskId })).resolves.toEqual({
            taskId,
            runId: RUN.id,
        })
        expect(calls.filter((call) => call.method === 'POST' && call.url.endsWith('/tasks/'))).toHaveLength(1)
        expect(calls.filter((call) => call.method === 'DELETE')).toEqual([])
    })

    test('after a restart, the report claim recovers the task whose first run never started', async () => {
        replies = [
            { ...REPORT, body: { ...(REPORT.body as object), assignee: { kind: 'task', task_id: 'task-1' } } },
            { status: 200, body: { id: 'task-1', signal_report: 'rep-1', latest_run: null } },
            { status: 200, body: { run: RUN } },
        ]
        await expect(kickOffReportTask('rep-1', { run: RUN_FIELDS })).resolves.toEqual({
            taskId: 'task-1',
            runId: RUN.id,
        })
        expect(calls.filter((call) => call.method === 'POST' && call.url.endsWith('/tasks/'))).toEqual([])
        expect(calls.at(-1)?.url).toContain('/tasks/task-1/run/')
    })

    test('an ambiguous failure adopts the run the original request started', async () => {
        const created = { id: 'task-1', title: 'Legend crash', signal_report: 'rep-1', latest_run: RUN }
        replies = [REPORT, { status: 200, body: created }]
        await expect(kickOffReportTask('rep-1', { run: RUN_FIELDS, taskId: 'task-1' })).resolves.toEqual({
            taskId: 'task-1',
            runId: RUN.id,
        })
        expect(calls.every((call) => call.method === 'GET')).toBe(true)
    })

    test('a warm sandbox refusal is retried with the first retry token', async () => {
        const clock = fakeClock()
        replies = [
            REPORT,
            WARM_UNAVAILABLE('tok-1'),
            WARM_UNAVAILABLE('tok-2'),
            { status: 201, body: { id: 'task-1', title: 'Legend crash', signal_report: 'rep-1', latest_run: RUN } },
        ]
        await kickOffReportTask('rep-1', { run: RUN_FIELDS, clock })
        expect(calls.slice(1).map((call) => call.headers['X-PostHog-Warm-Retry'])).toEqual([
            undefined,
            'tok-1',
            'tok-1',
        ])
        expect(clock.delays).toEqual([250, 500])
    })

    test('warm retries stop after 20 seconds', async () => {
        const clock = fakeClock()
        replies = [REPORT, ...Array.from({ length: 40 }, () => WARM_UNAVAILABLE('tok'))]
        await expect(kickOffReportTask('rep-1', { run: RUN_FIELDS, clock })).rejects.toMatchObject({
            status: 503,
            code: 'warm_run_activation_unavailable',
        })
        expect(clock.delays.reduce((sum, ms) => sum + ms, 0)).toBe(20_000)
    })

    test.each<[string, unknown, string]>([
        [
            'free trial uses the server copy',
            new ApiError(402, { code: 'self_driving_free_trial', detail: 'Trial orgs get reports, not PRs.' }),
            'Trial orgs get reports, not PRs.',
        ],
        [
            'PR limit uses the server copy',
            new ApiError(402, { code: 'quota_limit_exceeded', detail: 'Your organization reached its limit.' }),
            'Your organization reached its limit.',
        ],
        [
            'a 402 without copy explains the PR limit',
            new ApiError(402, {}),
            'Your organization reached its self-driving pull request limit. Ask an org admin to raise it from the Inbox usage widget.',
        ],
        [
            'report task cap reads the error field',
            new ApiError(429, {
                type: 'rate_limit',
                code: 'signal_report_task_cap',
                error: 'This report has 3 tasks already.',
            }),
            'This report has 3 tasks already.',
        ],
        [
            'throttle reads detail',
            new ApiError(429, { code: 'throttled', detail: 'Try again in 30 seconds.' }),
            'Try again in 30 seconds.',
        ],
        [
            'task cap without copy',
            new ApiError(429, { code: 'signal_report_task_cap' }),
            'Task limit reached for this report. Try again later.',
        ],
        ['another server error', new ApiError(500, {}), "Couldn't hand off to PostHog. Try again."],
        [
            'a network failure',
            new TypeError('Network request failed'),
            "Couldn't reach PostHog. Check your connection and try again.",
        ],
    ])('handoffErrorMessage: %s', (_name, error, expected) => {
        expect(handoffErrorMessage(error)).toBe(expected)
    })
})
