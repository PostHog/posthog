import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { taskComputeCostLogic } from './taskComputeCostLogic'

describe('taskComputeCostLogic', () => {
    it.each([
        ['an AI credits origin', 'posthog_ai', 0.3],
        ['a PostHog Desktop origin', 'user_created', 0],
    ])('reports the compute of %s', async (_name, originProduct, expected) => {
        useMocks({
            get: {
                '/api/projects/:team_id/tasks/task-1/': { id: 'task-1', origin_product: originProduct },
                '/api/projects/:team_id/tasks/task-1/usage/': {
                    token_cost_usd: 1,
                    compute_cost_usd: 0.3,
                    total_cost_usd: 1.3,
                },
            },
        })
        initKeaTests()
        const logic = taskComputeCostLogic({ taskId: 'task-1' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadComputeCost()).toFinishAllListeners()

        expect(logic.values.computeCostUsd).toBe(expected)
        logic.unmount()
    })
})
