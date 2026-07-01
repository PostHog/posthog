import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { OriginProduct } from '../../types/taskTypes'
import { taskTrackerSceneLogic } from './taskTrackerSceneLogic'

describe('taskTrackerSceneLogic', () => {
    let logic: ReturnType<typeof taskTrackerSceneLogic.build>
    let createBody: Record<string, any> | null
    let runCalled: boolean

    beforeEach(() => {
        createBody = null
        runCalled = false
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
                '/api/projects/:team/tasks/:id/run/': () => {
                    runCalled = true
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
        expect(runCalled).toBe(true)
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
})
