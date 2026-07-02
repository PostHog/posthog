import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { OriginProduct } from '../../types/taskTypes'
import { taskTrackerSceneLogic } from './taskTrackerSceneLogic'

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
})
