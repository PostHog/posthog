import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { subscriptionsList } from 'products/subscriptions/frontend/generated/api'

import { subscriptionCountLogic } from './subscriptionCountLogic'

jest.mock('products/subscriptions/frontend/generated/api', () => ({
    subscriptionsList: jest.fn(),
}))

const mockSubscriptionsList = subscriptionsList as jest.Mock

describe('subscriptionCountLogic', () => {
    let logic: ReturnType<typeof subscriptionCountLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockSubscriptionsList.mockReset()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the team-wide count from the response count field on mount', async () => {
        // count (full team total) differs from results.length to catch a results.length regression.
        mockSubscriptionsList.mockResolvedValue({ count: 3, results: [{ id: 1 }] })
        logic = subscriptionCountLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ subscriptionCount: 3 })
        // Lock in the limit=1 invariant — we only need the count, not the rows.
        expect(subscriptionsList).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ limit: 1 }))
    })

    it('loads zero for a team with no subscriptions', async () => {
        mockSubscriptionsList.mockResolvedValue({ count: 0, results: [] })
        logic = subscriptionCountLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ subscriptionCount: 0 })
    })

    it('falls back to 0 when the response omits count', async () => {
        mockSubscriptionsList.mockResolvedValue({ results: [] })
        logic = subscriptionCountLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ subscriptionCount: 0 })
    })
})
