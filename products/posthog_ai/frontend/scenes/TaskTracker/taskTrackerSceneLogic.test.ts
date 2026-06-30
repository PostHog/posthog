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
                '/api/projects/:team/integrations/': { results: [] },
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
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // PostHog AI can run without a repo: a description-only submit must still create and run the task with a
    // null repository, not bail. Guards against re-adding a "Repository is required" gate on the send path.
    it('creates and runs a task with no repository selected', async () => {
        logic.actions.setTaskCreateFormValues({ description: 'do the thing' })
        logic.actions.submitTaskCreateForm()

        await expectLogic(logic).toFinishAllListeners()

        expect(createBody).toMatchObject({ description: 'do the thing', repository: null, github_integration: null })
        expect(runCalled).toBe(true)
        expect(router.values.location.pathname).toContain('/tasks/new-task')
    })

    it('sends origin_product posthog_ai when creating a task from the composer', async () => {
        logic.actions.setTaskCreateFormValues({ description: 'Fix the bug' })
        logic.actions.submitTaskCreateForm()

        await expectLogic(logic).toFinishAllListeners()

        expect(createBody).toMatchObject({ origin_product: OriginProduct.POSTHOG_AI })
    })
})
