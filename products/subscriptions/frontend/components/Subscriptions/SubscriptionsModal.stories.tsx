import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useRef, useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { uuid } from 'lib/utils/dom'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { createMockSubscription, mockBasicUser, mockIntegration, mockSlackChannels } from '~/test/mocks'
import { DashboardType, InsightShortId, Realm, SubscriptionType } from '~/types'

import { SubscriptionsModal, SubscriptionsModalProps } from './SubscriptionsModal'

type StoryArgs = SubscriptionsModalProps & {
    formScenario?: 'default' | 'ai-summary-limit' | 'free-tier-limit'
}

const DASHBOARD = {
    id: 1,
    name: 'Weekly metrics',
    tiles: [
        { id: 1, insight: { id: 11, short_id: 'ins11' as InsightShortId } },
        { id: 2, insight: { id: 12, short_id: 'ins12' as InsightShortId } },
    ],
} as unknown as DashboardType

const DASHBOARD_SUBSCRIPTIONS = [
    createMockSubscription({
        id: 11,
        resource_type: 'dashboard',
        dashboard: 1,
        title: 'Weekly dashboard snapshot',
        target_type: 'slack',
        target_value: 'C123|#product-updates',
        summary: 'sent every week on monday',
        created_by: mockBasicUser,
    }),
    createMockSubscription({
        id: 12,
        resource_type: 'dashboard',
        dashboard: 1,
        title: 'Daily metrics email',
        target_type: 'email',
        target_value: 'metrics@posthog.com',
        summary: 'sent every day',
        created_by: mockBasicUser,
    }),
    createMockSubscription({
        id: 13,
        resource_type: 'dashboard',
        dashboard: 1,
        title: 'Monthly leadership report',
        summary: 'sent every month on the first day',
        target_type: 'email',
        target_value: 'leadership@posthog.com,finance@posthog.com,product@posthog.com',
        created_by: mockBasicUser,
    }),
    createMockSubscription({
        id: 14,
        resource_type: 'dashboard',
        dashboard: 1,
        title: 'Friday product review',
        target_type: 'slack',
        target_value: 'C456|#product-review',
        summary: 'sent every week on friday',
        created_by: mockBasicUser,
    }),
    createMockSubscription({
        id: 15,
        resource_type: 'dashboard',
        dashboard: 1,
        title: 'Paused dashboard digest',
        summary: 'sent every week on monday',
        target_type: 'email',
        target_value: 'archive@posthog.com',
        enabled: false,
        created_by: mockBasicUser,
    }),
]

const INSIGHT_SUBSCRIPTIONS = [
    createMockSubscription({
        id: 21,
        resource_type: 'insight',
        insight: 11,
        insight_short_id: 'ins11',
        resource_name: 'Weekly active users',
        title: 'Weekly active users snapshot',
        target_type: 'slack',
        target_value: 'C111|#growth-metrics',
        created_by: mockBasicUser,
    }),
    createMockSubscription({
        id: 22,
        resource_type: 'insight',
        insight: 12,
        insight_short_id: 'ins12',
        resource_name: 'Activation rate',
        title: 'Daily activation update',
        target_type: 'email',
        target_value: 'growth@posthog.com',
        summary: 'sent every day',
        created_by: mockBasicUser,
    }),
    createMockSubscription({
        id: 23,
        resource_type: 'insight',
        insight: 13,
        insight_short_id: 'ins13',
        resource_name: 'Customer retention',
        title: 'Monthly retention review',
        target_type: 'email',
        target_value: 'success@posthog.com,product@posthog.com',
        summary: 'sent every month on the first day',
        created_by: mockBasicUser,
    }),
    createMockSubscription({
        id: 24,
        resource_type: 'insight',
        insight: 14,
        insight_short_id: 'ins14',
        resource_name: 'Revenue growth',
        title: 'Friday revenue snapshot',
        target_type: 'slack',
        target_value: 'C789|#revenue',
        summary: 'sent every week on friday',
        created_by: mockBasicUser,
    }),
    createMockSubscription({
        id: 25,
        resource_type: 'insight',
        insight: 15,
        insight_short_id: 'ins15',
        resource_name: 'Trial conversion',
        title: 'Paused conversion report',
        target_type: 'slack',
        target_value: 'C222|#conversion-alerts,C333|#growth-review',
        enabled: false,
        created_by: mockBasicUser,
    }),
]

const AI_PROMPT_SUBSCRIPTIONS = [
    createMockSubscription({
        id: 21,
        resource_type: 'ai_prompt',
        title: 'Weekly product health report',
        prompt: 'Summarize activation, retention, and revenue changes from the last week.',
        target_type: 'slack',
        target_value: 'C123|#product-updates',
        summary: 'sent every week on monday',
        created_by: mockBasicUser,
    }),
    createMockSubscription({
        id: 22,
        resource_type: 'ai_prompt',
        title: 'Daily anomaly check',
        prompt: 'Find unusual changes in our key product metrics and explain likely causes.',
        summary: 'sent every day',
        created_by: { ...mockBasicUser, first_name: 'Ada', email: 'ada@posthog.com' },
    }),
]

const AI_PROMPT_PARAMETERS = {
    featureFlags: {
        [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]: true,
    },
}

const meta: Meta<StoryArgs> = {
    title: 'Products/Subscriptions/Subscriptions modal',
    component: SubscriptionsModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-31 12:00:00',
    },
    argTypes: {
        formScenario: {
            control: 'select',
            options: ['default', 'ai-summary-limit', 'free-tier-limit'],
        },
    },
    render: (args) => {
        const { formScenario = 'default', ...props } = args
        const aiSummaryAtLimit = formScenario === 'ai-summary-limit'
        const freeTierSubscriptionCount = formScenario === 'free-tier-limit' ? 5 : undefined
        const insightShortIdRef = useRef(props.insightShortId || (uuid() as InsightShortId))
        // Dashboard-context stories must not also pass an insight, or the modal renders the insight flow.
        const insightShortId = props.dashboard ? undefined : insightShortIdRef.current
        const [modalOpen, setModalOpen] = useState(false)
        const contextualSubscriptions: SubscriptionType[] = props.dashboard
            ? DASHBOARD_SUBSCRIPTIONS
            : INSIGHT_SUBSCRIPTIONS
        const dashboardInsightSubscriptions: SubscriptionType[] = INSIGHT_SUBSCRIPTIONS

        useStorybookMocks({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    realm: Realm.Cloud,
                    email_service_available: true,
                    slack_service: { available: true, client_id: 'test-client-id' },
                    site_url: window.location.origin,
                },
                '/api/organizations/@current/': {
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: true,
                },
                '/api/environments/:id/subscriptions': ({ request }) => {
                    const searchParams = new URL(request.url).searchParams
                    let results = contextualSubscriptions

                    if (searchParams.get('resource_type') === 'ai_prompt') {
                        results = AI_PROMPT_SUBSCRIPTIONS
                    } else if (searchParams.has('dashboard_tiles')) {
                        results = dashboardInsightSubscriptions
                    }

                    return { count: results.length, results }
                },
                '/api/environments/:id/subscriptions/:subId': createMockSubscription(),
                ...(freeTierSubscriptionCount !== undefined
                    ? { '/api/projects/:id/subscriptions/': { count: freeTierSubscriptionCount, results: [] } }
                    : {}),
                '/api/projects/:id/subscriptions/summary_quota': aiSummaryAtLimit
                    ? { active_count: 10, limit: 10, at_limit: true }
                    : { active_count: 0, limit: 10, at_limit: false },
                '/api/projects/:id/integrations': { results: [mockIntegration] },
                '/api/projects/:id/integrations/:intId/channels': { channels: mockSlackChannels },
            },
        })

        return (
            <div>
                <div className="p-4 bg-border">
                    <SubscriptionsModal
                        {...(props as SubscriptionsModalProps)}
                        closeModal={() => {
                            // eslint-disable-next-line no-console
                            console.log('close')
                        }}
                        insightShortId={insightShortId}
                        isOpen={true}
                        inline
                    />
                </div>

                <div className="flex justify-center mt-4">
                    <LemonButton onClick={() => setModalOpen(true)} type="primary">
                        Open as Modal
                    </LemonButton>
                </div>

                <SubscriptionsModal
                    {...(props as SubscriptionsModalProps)}
                    closeModal={() => setModalOpen(false)}
                    insightShortId={insightShortId}
                    isOpen={modalOpen}
                />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<StoryArgs>

export const SubscriptionsNew: Story = {
    args: { subscriptionId: 'new', formScenario: 'default' },
}

// Tabbed overview (feature flag on), dashboard context: This dashboard / Insights / AI prompt reports tabs.
export const SubscriptionsTabbed: Story = {
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.SUBSCRIPTION_TABBED_OVERVIEW]: 'test',
            [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]: true,
        },
    },
    args: {
        dashboard: DASHBOARD,
    },
}

export const DashboardWithSubscriptions: Story = {
    parameters: AI_PROMPT_PARAMETERS,
    args: { dashboard: DASHBOARD },
}

export const InsightWithSubscriptions: Story = {
    parameters: AI_PROMPT_PARAMETERS,
    args: { insightShortId: 'ins11' as InsightShortId },
}
