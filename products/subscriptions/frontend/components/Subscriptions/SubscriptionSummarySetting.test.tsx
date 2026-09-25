import { fireEvent, render, screen } from '@testing-library/react'
import { Form } from 'kea-forms'
import posthog from 'posthog-js'

import { useFeatureFlagVariantKey } from '@posthog/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { subscriptionLogic } from './subscriptionLogic'
import { SubscriptionSummarySetting } from './SubscriptionSummarySetting'

jest.mock('posthog-js')
jest.mock('@posthog/react', () => ({ useFeatureFlagVariantKey: jest.fn() }))

const logicProps = { id: 'new' as const, creationSource: 'wizard' as const }

describe('SubscriptionSummarySetting', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        useMocks({
            get: {
                '/api/environments/:team/subscriptions/summary_quota': {
                    active_count: 0,
                    limit: null,
                    at_limit: false,
                },
            },
        })
    })

    it.each([
        ['control', 'Include an automatic AI summary'],
        ['summary', 'Include a report summary'],
    ])('tracks user changes under the %s copy', (variant, label) => {
        jest.mocked(useFeatureFlagVariantKey).mockReturnValue(variant)
        const logic = subscriptionLogic(logicProps)
        logic.mount()

        render(
            <Form logic={logic} formKey="subscription">
                <SubscriptionSummarySetting logicProps={logicProps} />
            </Form>
        )

        const toggle = screen.getByRole('switch', { name: new RegExp(label) })
        expect(posthog.capture).not.toHaveBeenCalledWith('subscription summary toggled', expect.anything())

        fireEvent.click(toggle)
        expect(logic.values.subscription.summary_enabled).toBe(true)
        expect(posthog.capture).toHaveBeenCalledWith('subscription summary toggled', { enabled: true })

        fireEvent.click(toggle)
        expect(logic.values.subscription.summary_enabled).toBe(false)
        expect(posthog.capture).toHaveBeenCalledWith('subscription summary toggled', { enabled: false })
        logic.unmount()
    })
})
