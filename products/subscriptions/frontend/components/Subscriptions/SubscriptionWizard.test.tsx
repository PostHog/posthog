import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { SubscriptionResourceTypes } from '~/types'

import type { SubscriptionForm } from './subscriptionLogic'
import { SubscriptionReviewStep } from './SubscriptionWizard'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: () => ({ generatePreview: jest.fn() }),
    useValues: jest.fn(() => ({
        previewError: null,
        previewImageUrl: null,
        previewLoading: false,
        proactiveConfigurationOptions: {
            proactive_available: true,
            public_web_research_available: true,
            draft_pr_available: true,
            repositories: [],
        },
    })),
}))

describe('SubscriptionReviewStep', () => {
    afterEach(cleanup)

    const subscription = {
        id: 0,
        resource_type: SubscriptionResourceTypes.AiPrompt,
        title: 'Activation review',
        prompt: 'Find the biggest activation drop-off.',
        ai_prompt_config: { window: { mode: 'since_last_sent' } },
        proactive_config: {
            enabled: true,
            allow_public_web_research: true,
            create_draft_pr: true,
            repository: 'PostHog/posthog',
            repository_integration_id: 42,
        },
        target_value: 'product@example.com',
        target_type: 'email',
        frequency: 'weekly',
        interval: 1,
        start_date: '2026-08-31T09:00:00Z',
        byweekday: ['monday'],
        bysetpos: null,
        summary: 'sent every week',
        next_delivery_date: '2026-09-07T09:00:00Z',
        created_at: '2026-08-31T09:00:00Z',
        send_test_now: false,
    } satisfies SubscriptionForm

    it('shows the follow-up actions that will run after an AI report', () => {
        render(
            <SubscriptionReviewStep
                logicProps={{ id: 'new', proactiveSettingsEnabled: true }}
                subscription={subscription}
                dashboard={null}
            />
        )

        expect(screen.getByText('Actions')).toBeInTheDocument()
        expect(
            screen.getByText('Follow-up recommendations · Public web research · Draft pull request: PostHog/posthog')
        ).toBeInTheDocument()
    })

    it('omits actions if the feature is disabled before review', () => {
        render(<SubscriptionReviewStep logicProps={{ id: 'new' }} subscription={subscription} dashboard={null} />)

        expect(screen.queryByText('Actions')).not.toBeInTheDocument()
    })

    it('omits unavailable public research from the review', () => {
        jest.mocked(useValues).mockReturnValueOnce({
            previewError: null,
            previewImageUrl: null,
            previewLoading: false,
            proactiveConfigurationOptions: {
                proactive_available: true,
                public_web_research_available: false,
                draft_pr_available: true,
                repositories: [],
            },
        })

        render(
            <SubscriptionReviewStep
                logicProps={{ id: 'new', proactiveSettingsEnabled: true }}
                subscription={subscription}
                dashboard={null}
            />
        )

        expect(screen.getByText('Follow-up recommendations · Draft pull request: PostHog/posthog')).toBeInTheDocument()
    })
})
