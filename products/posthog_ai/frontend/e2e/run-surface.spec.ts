// Task and run API responses are mocked so the browser can hold creation, metadata, and stream
// transitions independently. Login, project, and feature flags use the real workspace harness.

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
// folds it into an inline error card titled "Run stopped".
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
    await expect(page.getByRole('heading', { name: 'Run surface e2e task', exact: true })).toBeVisible({
        timeout: 40000,
    })
}

async function prepareRunComposer(page: Page): Promise<void> {
    await page.addInitScript(() => {
        let appContext: {
            current_user?: {
                organization?: { is_ai_data_processing_approved?: boolean }
                has_seen_product_intro_for?: Record<string, boolean>
            }
        }
        Object.defineProperty(window, 'POSTHOG_APP_CONTEXT', {
            configurable: true,
            get: () => appContext,
            set: (value: typeof appContext) => {
                if (value.current_user?.organization) {
                    value.current_user.organization.is_ai_data_processing_approved = true
                }
                if (value.current_user) {
                    value.current_user.has_seen_product_intro_for = {
                        ...value.current_user.has_seen_product_intro_for,
                        posthog_ai_onboarding: true,
                    }
                }
                appContext = value
            },
        })
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
        // Regression: a terminal run's persisted `_posthog/error` frame must fold into the inline "Run stopped"
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

        await expect(page.getByText('Run stopped')).toBeVisible({ timeout: 20000 })
    })

    test('refresh restores the startup queue as a draft without sending it when the agent becomes ready', async ({
        page,
    }, testInfo) => {
        const firstMessage = 'Compare weekly activity.'
        const followUp = 'Include a monthly comparison.'
        const draft = 'Keep this unfinished draft.'
        const restoredDraft = `${followUp}\n\n${draft}`
        const commands: { method: string; params: { content?: string } }[] = []
        await prepareRunComposer(page)
        await routeTasksApi(page, {
            runStatus: 'queued',
            logs: { status: 200, body: '' },
            stream: { mode: 'hang' },
        })
        await page.route(
            (url) => url.pathname.endsWith(`/tasks/${TASK_ID}/`),
            fulfillJson({ ...makeTask('queued'), created_by: null })
        )
        await page.route(
            (url) => url.pathname.endsWith(`/runs/${RUN_ID}/`),
            fulfillJson({
                ...makeRun('queued'),
                state: { pending_user_message: firstMessage, pending_user_message_id: 'pending-first-message' },
            })
        )
        await page.route(
            (url) => url.pathname.endsWith(`/runs/${RUN_ID}/command/`),
            async (route) => {
                commands.push(route.request().postDataJSON())
                await fulfillJson({ jsonrpc: '2.0', result: { queued: true } })(route)
            }
        )

        await openRunDeepLink(page, workspace!.team_id)
        await expect(page.getByText(firstMessage, { exact: true })).toBeVisible()
        const composer = page.getByTestId('sandbox-composer-input')
        await composer.fill(followUp)
        await composer.press('Enter')
        await expect(page.getByText('Up next', { exact: true })).toBeVisible()
        await expect(page.getByText(followUp, { exact: true })).toBeVisible()

        let startAgent!: () => void
        const agentReady = new Promise<void>((resolve) => {
            startAgent = resolve
        })
        await page.route(
            (url) => new RegExp(`/runs/${RUN_ID}/stream/?$`).test(url.pathname),
            async (route) => {
                await agentReady
                await route.fulfill({
                    contentType: 'text/event-stream',
                    body: toSse([
                        {
                            type: 'notification',
                            notification: { method: '_posthog/run_started', params: { runId: RUN_ID } },
                        },
                        {
                            type: 'notification',
                            notification: { method: '_posthog/user_message', params: { content: firstMessage } },
                        },
                        agentMessageFrame('first-answer', 'Start by grouping activity by week.'),
                        { type: 'notification', notification: { method: '_posthog/turn_complete', params: {} } },
                    ]),
                })
            }
        )
        await composer.fill(draft)
        await page.reload()
        await expect(composer).toHaveValue(restoredDraft, { timeout: 40000 })
        await expect(page.getByTestId('task-draft-restored')).toHaveText('Draft restored. Review it before sending.')
        await expect(page.getByText('Up next', { exact: true })).toHaveCount(0)
        await expect(page.getByText(firstMessage, { exact: true })).toBeVisible()

        startAgent()
        await expect(page.getByText('Start by grouping activity by week.', { exact: true })).toBeVisible()
        await expect(page.getByText(firstMessage, { exact: true })).toHaveCount(1)
        await expect(composer).toHaveValue(restoredDraft)
        expect(commands).toEqual([])
        await page.screenshot({ path: testInfo.outputPath('restored-task-draft.png') })

        await composer.press('Enter')
        await expect(composer).toHaveValue('')
        await expect(page.getByTestId('task-draft-restored')).toHaveCount(0)
        await expect
            .poll(() =>
                commands.filter((command) => command.method === 'user_message').map((command) => command.params.content)
            )
            .toEqual([restoredDraft])
    })

    for (const [surface, path] of [
        ['task page', 'tasks/new'],
        ['side panel', 'settings/user#panel=max'],
    ]) {
        test(`new tasks start optimistically and recover from failure in the ${surface}`, async ({ page }) => {
            const message = 'Explain how to compare weekly activity.'
            const followUp = 'Include a monthly comparison.'
            const draft = 'Keep this unfinished draft.'
            let finishCreation!: (succeeded: boolean) => void
            let creationResponse = new Promise<boolean>((resolve) => {
                finishCreation = resolve
            })
            let revealMetadata!: () => void
            const metadataReady = new Promise<void>((resolve) => {
                revealMetadata = resolve
            })
            let startAgent!: () => void
            const agentReady = new Promise<void>((resolve) => {
                startAgent = resolve
            })
            await prepareRunComposer(page)
            await mockFeatureFlags(page, {
                [TASKS_FLAG]: true,
                [TASKS_STREAM_VIA_PROXY_FLAG]: false,
                'phai-sandbox-mode': true,
            })
            await routeTasksApi(page, {
                runStatus: 'queued',
                logs: { status: 200, body: '' },
                stream: { mode: 'hang' },
            })
            await page.route(
                (url) => url.pathname.endsWith('/tasks/'),
                async (route) => {
                    if (route.request().method() === 'GET') {
                        await fulfillJson({ results: [], count: 0 })(route)
                        return
                    }
                    const succeeded = await creationResponse
                    await route.fulfill({
                        status: succeeded ? 201 : 500,
                        contentType: 'application/json',
                        body: JSON.stringify(
                            succeeded ? { ...makeTask('queued'), latest_run: null } : { detail: 'Failed' }
                        ),
                    })
                }
            )
            await page.route(
                (url) => url.pathname.endsWith(`/runs/${RUN_ID}/command/`),
                fulfillJson({ jsonrpc: '2.0', result: { queued: true } })
            )
            await page.route((url) => url.pathname.endsWith('/tasks/repositories/'), fulfillJson({ repositories: [] }))
            await page.route(
                (url) => url.pathname.endsWith('/tasks/warm/'),
                (route) => route.fulfill({ status: 503 })
            )
            await page.route((url) => url.pathname.endsWith(`/tasks/${TASK_ID}/run/`), fulfillJson(makeTask('queued')))
            await page.route(
                (url) => url.pathname.endsWith(`/tasks/${TASK_ID}/`),
                async (route) => {
                    await metadataReady
                    await fulfillJson({ ...makeTask('queued'), created_by: null })(route)
                }
            )
            await page.route(
                (url) => new RegExp(`/runs/${RUN_ID}/stream/?$`).test(url.pathname),
                async (route) => {
                    await agentReady
                    await route.fulfill({
                        contentType: 'text/event-stream',
                        body: toSse([
                            {
                                type: 'notification',
                                notification: { method: '_posthog/run_started', params: { runId: RUN_ID } },
                            },
                            {
                                type: 'notification',
                                notification: { method: '_posthog/user_message', params: { content: message } },
                            },
                            agentMessageFrame('first-answer', 'Start by grouping activity by week.'),
                            { type: 'notification', notification: { method: '_posthog/turn_complete', params: {} } },
                        ]),
                    })
                }
            )

            await page.goto(`/project/${workspace!.team_id}/${path}`)
            const composer = page.getByTestId('task-composer-input')
            await expect(composer).toBeVisible({ timeout: 40000 })
            await composer.fill(message)
            await composer.press('Enter')
            await expect(page.getByText(message, { exact: true })).toBeVisible()
            await expect(page.getByText('Setting up sandbox', { exact: false })).toBeVisible()
            await expect(page.getByTestId('run-log-skeleton')).toHaveCount(0)

            const followUpComposer = page.getByTestId('sandbox-composer-input')
            await expect(followUpComposer).toBeVisible()
            await expect(page.getByRole('combobox', { name: 'Mode', exact: true })).toBeVisible()
            await followUpComposer.fill(followUp)
            await followUpComposer.press('Enter')
            await expect(page.getByText('Up next', { exact: true })).toBeVisible()
            await expect(page.getByText(followUp, { exact: true })).toBeVisible()
            await expect(page.getByTestId('run-queue-steer')).toBeDisabled()
            await followUpComposer.fill(draft)
            finishCreation(false)
            await expect(composer).toHaveValue(`${message}\n\n${followUp}\n\n${draft}`)
            await composer.fill(message)
            await expect(page.getByText('Setting up sandbox', { exact: false })).toHaveCount(0)
            creationResponse = new Promise<boolean>((resolve) => {
                finishCreation = resolve
            })
            await composer.press('Enter')
            await expect(page.getByText(message, { exact: true })).toBeVisible()
            await expect(followUpComposer).toBeVisible()
            await followUpComposer.fill(followUp)
            await followUpComposer.press('Enter')
            await expect(page.getByText('Up next', { exact: true })).toBeVisible()
            await followUpComposer.fill(draft)
            finishCreation(true)

            await expect(page.getByTestId('sandbox-composer-input')).toBeVisible()
            await expect(page.getByText(message, { exact: true })).toHaveCount(1)
            await expect(page.getByText('Setting up sandbox', { exact: false })).toBeVisible()
            await expect(page.getByTestId('run-log-skeleton')).toHaveCount(0)
            await expect(followUpComposer).toHaveValue(draft)
            await expect(followUpComposer).toBeFocused()
            await expect(page.getByText('Up next', { exact: true })).toBeVisible()
            await expect(page.getByTestId('run-queue-steer')).toBeDisabled()
            await page.screenshot({ path: test.info().outputPath('new-task-starting.png') })

            startAgent()
            await expect(page.getByText('Start by grouping activity by week.', { exact: true })).toBeVisible()
            await expect(page.getByText(message, { exact: true })).toHaveCount(1)
            await expect(page.getByText('Up next', { exact: true })).toHaveCount(0)
            await expect(page.getByText(followUp, { exact: true })).toHaveCount(1)
            await expect(followUpComposer).toHaveValue(draft)
            revealMetadata()
            await expect(page.getByTestId('sandbox-composer-input')).toBeVisible()
            await expect(page.getByTestId('run-log-skeleton')).toHaveCount(0)
        })
    }

    test('resuming a finished sandbox keeps the thread and pending message visible', async ({ page }) => {
        const successorId = '0190a000-0000-4000-8000-0000000000c3'
        const successor = { ...makeRun('queued'), id: successorId, state: { resume_from_run_id: RUN_ID } }
        let acceptRun!: () => void
        const runAccepted = new Promise<void>((resolve) => {
            acceptRun = resolve
        })
        let startAgent!: () => void
        const agentStarted = new Promise<void>((resolve) => {
            startAgent = resolve
        })

        await routeTasksApi(page, {
            runStatus: 'completed',
            logs: {
                status: 200,
                body: toJsonl([
                    {
                        type: 'notification',
                        notification: {
                            method: '_posthog/progress',
                            params: {
                                group: `setup:${RUN_ID}`,
                                step: 'agent',
                                status: 'completed',
                                label: 'Started agent',
                            },
                        },
                    },
                    agentMessageFrame('m1', 'The earlier answer stays here.'),
                    {
                        type: 'notification',
                        notification: {
                            method: 'session/update',
                            params: {
                                update: {
                                    sessionUpdate: 'usage_update',
                                    used: 12000,
                                    size: 1000000,
                                    cost: { amount: 0.04, currency: 'USD' },
                                },
                            },
                        },
                    },
                ]),
            },
            stream: { mode: 'hang' },
        })
        await prepareRunComposer(page)
        await page.route(
            (url) => url.pathname.endsWith(`/tasks/${TASK_ID}/`),
            fulfillJson({ ...makeTask('completed'), created_by: null })
        )
        await page.route(
            (url) => url.pathname.endsWith(`/tasks/${TASK_ID}/warm/`),
            fulfillJson({ run_id: successorId, task_id: TASK_ID })
        )
        await page.route(
            (url) => url.pathname.endsWith(`/tasks/${TASK_ID}/run/`),
            async (route) => {
                await runAccepted
                await fulfillJson({ ...makeTask('queued'), latest_run: successor })(route)
            }
        )
        await page.route((url) => url.pathname.endsWith(`/runs/${successorId}/`), fulfillJson(successor))
        await page.route(
            (url) => url.pathname.endsWith(`/runs/${successorId}/stream_token/`),
            fulfillJson({ token: 'e2e-token', stream_base_url: null })
        )
        await page.route(
            (url) => new RegExp(`/runs/${successorId}/stream/?$`).test(url.pathname),
            async (route) => {
                await agentStarted
                await route.fulfill({
                    contentType: 'text/event-stream',
                    body:
                        toSse([
                            {
                                type: 'notification',
                                notification: {
                                    method: '_posthog/progress',
                                    params: {
                                        group: `setup:${successorId}`,
                                        step: 'sandbox',
                                        status: 'completed',
                                        label: 'Restored sandbox',
                                    },
                                },
                            },
                            {
                                type: 'notification',
                                notification: {
                                    method: '_posthog/progress',
                                    params: {
                                        group: `setup:${successorId}`,
                                        step: 'agent',
                                        status: 'completed',
                                        label: 'Started agent',
                                    },
                                },
                            },
                            {
                                type: 'notification',
                                notification: { method: '_posthog/run_started', params: { runId: successorId } },
                            },
                            {
                                type: 'notification',
                                notification: {
                                    method: '_posthog/user_message',
                                    params: { content: 'Continue with the next step.' },
                                },
                            },
                            agentMessageFrame('m2', 'The next step is ready.'),
                        ]) + 'data: {"type":"task_run_state","status":"completed"}\n\n',
                })
            }
        )

        await openRunDeepLink(page, workspace!.team_id)
        await expect(page.getByText('The earlier answer stays here.', { exact: true })).toBeVisible({ timeout: 30000 })
        await expect(page.getByTestId('max-sandbox-context-usage')).toBeVisible()
        await expect(page.getByText('Started agent', { exact: true })).toBeVisible()
        const composer = page.getByTestId('sandbox-composer-input')
        await composer.fill('Continue with the next step.')
        await page.getByTestId('sandbox-composer-send').click()
        await expect(page.getByText('Continue with the next step.', { exact: true })).toHaveCount(1)
        await expect(page.getByText('Setting up sandbox', { exact: false })).toBeVisible()
        await expect(composer).toHaveValue('')
        await expect(page.getByTestId('max-sandbox-context-usage')).toBeVisible()
        await expect(page.getByTestId('sandbox-composer-send')).toBeDisabled()
        await expect(page.getByTestId('run-log-skeleton')).toHaveCount(0)

        await composer.fill('Keep this newer draft.')
        acceptRun()
        await expect(page.getByTestId('sandbox-composer-send')).toBeEnabled()
        await expect(composer).toHaveValue('Keep this newer draft.')
        await expect(page.getByTestId('max-sandbox-context-usage')).toBeVisible()
        await expect(page.getByText('The earlier answer stays here.', { exact: true })).toBeVisible()
        await expect(page.getByText('Continue with the next step.', { exact: true })).toHaveCount(1)
        await expect(page.getByText('Setting up sandbox', { exact: false })).toBeVisible()
        await expect(page.getByTestId('run-log-skeleton')).toHaveCount(0)

        startAgent()
        await expect(page.getByText('The next step is ready.', { exact: true })).toBeVisible()
        await expect(page.getByText('Continue with the next step.', { exact: true })).toHaveCount(1)
        await expect(page.getByText('Restored sandbox', { exact: true })).toHaveCount(0)
        await expect(page.getByText('Started agent', { exact: true })).toHaveCount(2)
        await page.getByRole('button', { name: 'Expand history', exact: true }).click()
        await expect(page.getByText('Restored sandbox', { exact: true })).toBeVisible()
        await page.screenshot({ path: test.info().outputPath('resumed-sandbox-startup-history.png') })
        await expect(composer).toHaveValue('Keep this newer draft.')
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
