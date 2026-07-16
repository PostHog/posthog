import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { attachedContextLogic } from '../../api/logics'
import { OriginProduct, Task, TaskRunEnvironment, TaskRunStatus } from '../../types/taskTypes'
import { taskTrackerSceneLogic } from './taskTrackerSceneLogic'

const buildTask = (overrides: Partial<Task> = {}): Task => ({
    id: 'task-1',
    task_number: 1,
    slug: 'task-1',
    title: 'Some task',
    description: 'do the thing',
    origin_product: OriginProduct.POSTHOG_AI,
    repository: null,
    github_integration: null,
    signal_report: null,
    json_schema: null,
    internal: false,
    latest_run: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    created_by: null,
    ...overrides,
})

describe('taskTrackerSceneLogic', () => {
    let logic: ReturnType<typeof taskTrackerSceneLogic.build>
    let createBody: Record<string, any> | null
    let runBody: Record<string, any> | null

    beforeEach(() => {
        createBody = null
        runBody = null
        useMocks({
            get: {
                '/api/projects/:team/tasks/': { results: [], count: 0 },
                '/api/projects/:team/tasks/repositories/': { repositories: [] },
                '/api/environments/:team/integrations/': { results: [] },
            },
            post: {
                '/api/projects/:team/tasks/': async ({ request }) => {
                    createBody = (await request.json()) as Record<string, any>
                    return [200, { id: 'new-task', ...createBody }]
                },
                '/api/projects/:team/tasks/:id/run/': async ({ request }) => {
                    runBody = (await request.json()) as Record<string, any>
                    return [200, { id: 'new-task' }]
                },
            },
        })
        initKeaTests()
        logic = taskTrackerSceneLogic()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // PostHog AI can run without a repo: a description-only submit must still create and run the task with a
    // null repository, not bail. Guards against re-adding a "Repository is required" gate on the send path.
    it('creates and runs a task with no repository selected', async () => {
        logic.mount()
        logic.actions.setNewTaskData({ description: 'do the thing' })
        logic.actions.submitNewTask()

        await expectLogic(logic).toFinishAllListeners()

        expect(createBody).toMatchObject({
            description: 'do the thing',
            origin_product: OriginProduct.POSTHOG_AI,
            repository: null,
            github_integration: null,
        })
        // Interactive so the sandbox event stream survives across turns (follow-ups stream), and the
        // typed message is seeded as turn 1 (interactive runs boot with the agent pulling it from run
        // state). Dropping either regresses follow-up streaming / loses the first prompt.
        expect(runBody).toMatchObject({
            mode: 'interactive',
            pending_user_message: 'do the thing',
        })
        expect(router.values.location.pathname).toContain('/tasks/new-task')
    })

    // The seeded first message wraps the on-screen context, and the wrapped non-text refs must be marked
    // sent under the created task's id — otherwise the run's first follow-up (sent via
    // `runInteractionLogic`, which prunes against the task-scoped store) re-wraps the same refs.
    it('marks seeded context sent for the created task so the first follow-up will not re-wrap it', async () => {
        logic.mount()
        attachedContextLogic().actions.registerContext('scene', [
            { type: 'insight', key: 'sig', label: 'Signups' },
            { type: 'text', value: 'always resend me' },
        ])

        logic.actions.setNewTaskData({ description: 'why the drop?' })
        logic.actions.submitNewTask()
        await expectLogic(logic).toFinishAllListeners()

        // The message sent to the agent is wrapped; the task description stays raw.
        expect(runBody?.pending_user_message).toContain('<posthog_context>')
        expect(runBody?.pending_user_message).toContain('- insight sig ("Signups")')
        expect(createBody?.description).toBe('why the drop?')
        // Only the entity ref is marked sent (text items always resend), under the created task's id.
        expect(attachedContextLogic().values.sentContextKeysByTask).toEqual({ 'new-task': ['insight:sig'] })
    })

    // The repo picker only renders once `repositoryConfig.integrationId` is set (auto-selected from the
    // connected GitHub org). Submitting resets the form, wiping that id; without re-deriving it the picker
    // stays blank for every subsequent new task. Guards that the auto-select is restored after a submit.
    it('restores the repository integration after a submit so the picker reappears', async () => {
        useMocks({
            get: {
                '/api/environments/:team/integrations/': {
                    results: [{ id: 7, kind: 'github', display_name: 'acme/widgets', config: {} }],
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        // Auto-selected on mount once the integration list loads — the picker is showing.
        expect(logic.values.newTaskData.repositoryConfig.integrationId).toBe(7)

        logic.actions.setNewTaskData({ description: 'ship it' })
        logic.actions.submitNewTask()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.newTaskData.repositoryConfig.integrationId).toBe(7)
    })

    // An embedded instance (e.g. Max's side panel runner) keeps the run in place instead of navigating the
    // host to `/tasks/:id`, and must never have its `activeCreation` cleared by unrelated main-app
    // navigation. Guards against either guard (`props.panelId` in `submitNewTask` / `urlToAction`) being
    // dropped, which would yank the host to the tasks scene or silently drop the panel's in-flight run.
    it('does not navigate on create and ignores url cleanup for an embedded instance', async () => {
        const panelLogic = taskTrackerSceneLogic({ panelId: 'test-panel' })
        panelLogic.mount()
        const initialPath = router.values.location.pathname

        panelLogic.actions.setNewTaskData({ description: 'do the thing' })
        panelLogic.actions.submitNewTask()
        await expectLogic(panelLogic).toFinishAllListeners()

        expect(router.values.location.pathname).toBe(initialPath)
        expect(panelLogic.values.activeCreation).toMatchObject({ taskId: 'new-task' })

        router.actions.push('/tasks/some-other-task')
        expect(panelLogic.values.activeCreation).toMatchObject({ taskId: 'new-task' })

        panelLogic.unmount()
    })

    // Opening a task from the panel's history must render its run in place (a task with a run) or fall
    // back to the full detail page (a task that never ran) — never the other way round.
    it.each([
        {
            description: 'a task with a latest run',
            task: buildTask({
                id: 'task-with-run',
                latest_run: {
                    id: 'run-1',
                    task: 'task-with-run',
                    stage: null,
                    branch: null,
                    status: TaskRunStatus.COMPLETED,
                    environment: TaskRunEnvironment.CLOUD,
                    log_url: null,
                    error_message: null,
                    output: null,
                    state: {},
                    artifacts: [],
                    created_at: '2026-01-01T00:00:00Z',
                    updated_at: '2026-01-01T00:00:00Z',
                    completed_at: '2026-01-01T00:00:00Z',
                },
            }),
            expectedActiveCreation: { streamKey: 'run-1', taskId: 'task-with-run', runId: 'run-1' },
            expectedPath: undefined,
        },
        {
            description: 'a task that never ran',
            task: buildTask({ id: 'task-without-run', latest_run: null }),
            expectedActiveCreation: null,
            expectedPath: '/tasks/task-without-run',
        },
    ])('openExistingTask opens $description', ({ task, expectedActiveCreation, expectedPath }) => {
        logic.mount()
        const initialPath = router.values.location.pathname
        // Set beforehand to prove opening a task resets it, even for the never-ran/navigate case.
        logic.actions.toggleHistory()
        expect(logic.values.historyExpanded).toBe(true)

        logic.actions.openExistingTask(task)

        expect(logic.values.activeCreation).toEqual(expectedActiveCreation)
        expect(logic.values.historyExpanded).toBe(false)
        expect(router.values.location.pathname).toContain(expectedPath ?? initialPath)
    })
})
