import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { AvailableFeature } from '~/types'

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
        userLogic.mount()
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            organization: { ...MOCK_DEFAULT_ORGANIZATION, available_product_features: [] },
        })
    })

    afterEach(() => {
        logic?.unmount()
        userLogic.unmount()
    })

    it.each([false, true])(
        'loads the count only without the subscription entitlement (available=%s)',
        async (available) => {
            userLogic.actions.loadUserSuccess({
                ...MOCK_DEFAULT_USER,
                organization: {
                    ...MOCK_DEFAULT_ORGANIZATION,
                    available_product_features: available
                        ? [{ key: AvailableFeature.SUBSCRIPTIONS, name: 'Subscriptions' }]
                        : [],
                },
            })
            // count (full team total) differs from results.length to catch a results.length regression.
            mockSubscriptionsList.mockResolvedValue({ count: 3, results: [{ id: 1 }] })
            logic = subscriptionCountLogic()
            logic.mount()

            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({ subscriptionCount: available ? null : 3 })
            if (available) {
                expect(subscriptionsList).not.toHaveBeenCalled()
            } else {
                expect(subscriptionsList).toHaveBeenCalledWith(
                    expect.any(String),
                    expect.objectContaining({ limit: 1 })
                )
            }
        }
    )

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
