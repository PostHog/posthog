// End-to-end coverage for the three run-surface connection states that only a real browser can prove:
// a terminal run's inline error card, the live reconnecting banner on a stream drop, and the terminal
// "Connection lost" card when the run history keeps failing. The whole tasks/runs API is mocked with
// `page.route` so each state is deterministic; everything else (login, project, feature flags) rides the
// real workspace harness, mirroring the surveys e2e precedent.

import { mockFeatureFlags } from '@playwright-utils/mockApi'
import { PlaywrightWorkspaceSetupResult, expect, test } from '@playwright-utils/workspace-test-base'
import { Page, Route } from '@playwright/test'

// Flag keys mirror `FEATURE_FLAGS.TASKS` / `FEATURE_FLAGS.TASKS_STREAM_VIA_PROXY` (frontend/src/lib/constants).
// Inlined as literals rather than imported: pulling `lib/constants` into a Node-run Playwright spec drags its
// heavy `types.ts` value-import graph into the test bundle. These keys are stable feature-flag wire strings.
const TASKS_FLAG = 'tasks'
const TASKS_STREAM_VIA_PROXY_FLAG = 'tasks-stream-via-proxy'

// Fixed UUIDs so the `?runId=` deep link clears `taskDetailSceneLogic`'s `isUUIDLike` guard deterministically.
const TASK_ID = '0190a000-0000-4000-8000-0000000000a1'
const RUN_ID = '0190a000-0000-4000-8000-0000000000b2'

interface AcpFrame {
    type: 'notification'
    timestamp?: string
    notification: Record<string, unknown>
}

interface StreamMock {
    // 'body' delivers the frames then EOFs (a clean-EOF live drop); 'hang' never responds so the SSE open
    // stalls short of `sseOpened` — used when a different signal (terminal status, exhausted history) should
    // drive the surface state without the reconnect loop flapping.
    mode: 'body' | 'hang'
    body?: string
}

interface TasksApiMock {
    runStatus: string
    logs: { status: number; body: string }
    stream: StreamMock
}

function agentMessageFrame(messageId: string, text: string): AcpFrame {
    return {
        type: 'notification',
        notification: {
            method: 'session/update',
            params: { update: { sessionUpdate: 'agent_message', messageId, content: { type: 'text', text } } },
        },
    }
}

// A persisted `_posthog/error` frame — the synthetic backend/agent error the run log carries; `foldLogToThread`
// folds it into an inline error card titled "Agent error".
function posthogErrorFrame(message: string): AcpFrame {
    return { type: 'notification', notification: { method: '_posthog/error', params: { message } } }
}

// The `logs/` endpoint replays JSONL — one `StoredLogEntry` per line.
function toJsonl(frames: AcpFrame[]): string {
    return frames.map((frame) => JSON.stringify(frame)).join('\n')
}

// The `stream/` endpoint is `text/event-stream` — one `data:` event per frame. No terminal `task_run_state`
// or `stream-end` sentinel, so once the atomic body is read the reader hits a clean EOF (a drop).
function toSse(frames: AcpFrame[]): string {
    return frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join('')
}

function makeRun(status: string): Record<string, unknown> {
    return {
        id: RUN_ID,
        task: TASK_ID,
        stage: null,
        branch: null,
        status,
        environment: 'cloud',
        log_url: null,
        error_message: null,
        output: null,
        state: {},
        artifacts: [],
        created_at: '2026-07-01T00:00:00Z',
        updated_at: '2026-07-01T00:00:00Z',
        completed_at: status === 'in_progress' ? null : '2026-07-01T00:01:00Z',
    }
}

function makeTask(status: string): Record<string, unknown> {
    return {
        id: TASK_ID,
        task_number: 1,
        slug: 'run-surface-e2e',
        title: 'Run surface e2e task',
        description: '',
        origin_product: 'user_created',
        repository: null,
        github_integration: null,
        json_schema: null,
        internal: false,
        latest_run: makeRun(status),
        created_at: '2026-07-01T00:00:00Z',
        updated_at: '2026-07-01T00:00:00Z',
        created_by: { id: 1, uuid: 'user-1', distinct_id: 'user-1', first_name: 'Test', email: 'test@posthog.com' },
    }
}

function fulfillJson(body: unknown): (route: Route) => Promise<void> {
    return (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
}

async function routeTasksApi(page: Page, mock: TasksApiMock): Promise<void> {
    const run = makeRun(mock.runStatus)
    // Each pattern is `$`-anchored on the pathname so it matches exactly one endpoint despite the shared
    // `/runs/:id/` prefix (mutually exclusive, so Playwright's route ordering doesn't matter).
    const taskRe = new RegExp(`/tasks/${TASK_ID}/$`)
    const runsRe = new RegExp(`/tasks/${TASK_ID}/runs/$`)
    const runRe = new RegExp(`/tasks/${TASK_ID}/runs/${RUN_ID}/$`)
    const tokenRe = new RegExp(`/runs/${RUN_ID}/stream_token/$`)
    const logsRe = new RegExp(`/runs/${RUN_ID}/logs/$`)
    // The `stream` action URL has no trailing slash (`.../stream?start=latest`), unlike the other
    // resource paths — match it with an optional slash so the route intercepts instead of falling through
    // to the real backend (a fall-through 404s the fake run id and masks the clean-EOF drop under test).
    const streamRe = new RegExp(`/runs/${RUN_ID}/stream/?$`)

    await page.route((url) => taskRe.test(url.pathname), fulfillJson(makeTask(mock.runStatus)))
    await page.route(
        (url) => runsRe.test(url.pathname),
        fulfillJson({ results: [run], count: 1, next: null, previous: null })
    )
    await page.route((url) => runRe.test(url.pathname), fulfillJson(run))
    // No `stream_base_url` ⇒ `resolveStreamTarget` returns null ⇒ streaming stays on the mockable Django
    // `stream/` route even when the proxy gate (flag or preflight `is_debug`) is on.
    await page.route((url) => tokenRe.test(url.pathname), fulfillJson({ token: 'e2e-token', stream_base_url: null }))
    await page.route(
        (url) => logsRe.test(url.pathname),
        (route) => route.fulfill({ status: mock.logs.status, contentType: 'application/jsonl', body: mock.logs.body })
    )

    if (mock.stream.mode === 'hang') {
        // Leave the request pending forever; the bootstrap aborts it once the history retries exhaust.
        await page.route(
            (url) => streamRe.test(url.pathname),
            () => new Promise<void>(() => {})
        )
    } else {
        const body = mock.stream.body ?? ''
        await page.route(
            (url) => streamRe.test(url.pathname),
            (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body })
        )
    }
}

async function openRunDeepLink(page: Page, teamId: string): Promise<void> {
    await page.goto(`/project/${teamId}/tasks/${TASK_ID}?runId=${RUN_ID}`)
    // The fresh workspace has no tasks flag; force posthog-js to re-fetch so the mocked flag lands and the
    // scene's `FEATURE_FLAGS.TASKS` gate opens.
    await page.evaluate(() => {
        const ph = (window as unknown as { posthog?: { reloadFeatureFlags?: () => void } }).posthog
        ph?.reloadFeatureFlags?.()
    })
}

test.describe('Task run surface', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
        await mockFeatureFlags(page, { [TASKS_FLAG]: true, [TASKS_STREAM_VIA_PROXY_FLAG]: false })
    })

    test('terminal replay surfaces the agent error inline', async ({ page }) => {
        // Regression: a terminal run's persisted `_posthog/error` frame must fold into the inline "Agent error"
        // card on replay — not be dropped, and not depend on a live SSE (a terminal run never opens one).
        await routeTasksApi(page, {
            runStatus: 'completed',
            logs: {
                status: 200,
                body: toJsonl([
                    agentMessageFrame('m1', 'Doing the thing'),
                    posthogErrorFrame('The agent hit an unexpected error'),
                ]),
            },
            stream: { mode: 'hang' },
        })

        await openRunDeepLink(page, workspace!.team_id)

        await expect(page.getByText('Agent error')).toBeVisible({ timeout: 20000 })
    })

    test('live stream drop shows the reconnecting banner', async ({ page }) => {
        // Regression: a clean-EOF drop on an in-progress run must surface the reconnecting banner (the backoff
        // loop) rather than silently stalling or reading as ordinary thinking.
        await routeTasksApi(page, {
            runStatus: 'in_progress',
            logs: { status: 200, body: toJsonl([agentMessageFrame('m1', 'Working on it')]) },
            stream: {
                mode: 'body',
                body: toSse([agentMessageFrame('s1', 'Streaming'), agentMessageFrame('s2', 'Still streaming')]),
            },
        })

        await openRunDeepLink(page, workspace!.team_id)

        // Assert only the first reconnecting window — `reconnectAttempt` resets to 0 on each reopen so the banner
        // cycles; a single visibility check on the title keeps it deterministic.
        await expect(page.getByText('Reconnecting to agent')).toBeVisible({ timeout: 20000 })
    })

    test('exhausted run history shows connection lost', async ({ page }) => {
        // Regression: exhausting the history-fetch retries on an in-progress run must tear the SSE down and
        // surface the terminal "Connection lost" card — not spin forever or render a live-only, historyless thread.
        await routeTasksApi(page, {
            runStatus: 'in_progress',
            logs: { status: 500, body: '' },
            // Stall the SSE open so only the exhausted history drives the terminal state (no reconnect flapping).
            stream: { mode: 'hang' },
        })

        await openRunDeepLink(page, workspace!.team_id)

        // The history retries back off ~2s + ~4s before giving up, so allow generous headroom.
        await expect(page.getByText('Connection lost')).toBeVisible({ timeout: 30000 })
    })
})
