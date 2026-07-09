import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useRef, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { uuid } from 'lib/utils/dom'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { createMockSubscription, mockIntegration, mockSlackChannels } from '~/test/mocks'
import { InsightShortId, Realm } from '~/types'

import { SubscriptionsModal, SubscriptionsModalProps } from './SubscriptionsModal'

type StoryArgs = SubscriptionsModalProps & {
    noIntegrations?: boolean
    aiSummaryAtLimit?: boolean
    // Team-wide subscription count for the free-tier create gate (under the limit → form, at/over → upsell).
    freeTierSubscriptionCount?: number
}

const meta: Meta<StoryArgs> = {
    title: 'Components/Subscriptions',
    component: SubscriptionsModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-31 12:00:00',
    },
    render: (args) => {
        const { noIntegrations = false, aiSummaryAtLimit = false, freeTierSubscriptionCount, ...props } = args
        const insightShortIdRef = useRef(props.insightShortId || (uuid() as InsightShortId))
        const [modalOpen, setModalOpen] = useState(false)

        useStorybookMocks({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    realm: Realm.Cloud,
                    email_service_available: noIntegrations ? false : true,
                    slack_service: noIntegrations
                        ? { available: false }
                        : { available: true, client_id: 'test-client-id' },
                    site_url: noIntegrations ? 'bad-value' : window.location.origin,
                },
                ...(aiSummaryAtLimit
                    ? {
                          '/api/organizations/@current/': {
                              ...MOCK_DEFAULT_ORGANIZATION,
                              is_ai_data_processing_approved: true,
                          },
                      }
                    : {}),
                '/api/environments/:id/subscriptions': {
                    results:
                        insightShortIdRef.current === 'empty'
                            ? []
                            : [
                                  createMockSubscription(),
                                  createMockSubscription({
                                      title: 'Weekly C-level report',
                                      target_value: 'james@posthog.com',
                                      frequency: 'weekly',
                                      interval: 1,
                                  }),
                                  createMockSubscription({
                                      title: 'Daily Slack report',
                                      target_type: 'slack',
                                      target_value: 'C123|#general',
                                      frequency: 'weekly',
                                      interval: 1,
                                  }),
                              ],
                },
                '/api/environments/:id/subscriptions/:subId': createMockSubscription(),
                ...(freeTierSubscriptionCount !== undefined
                    ? { '/api/projects/:id/subscriptions/': { count: freeTierSubscriptionCount, results: [] } }
                    : {}),
                '/api/projects/:id/subscriptions/summary_quota': aiSummaryAtLimit
                    ? { active_count: 10, limit: 10, at_limit: true }
                    : { active_count: 0, limit: 10, at_limit: false },
                '/api/projects/:id/integrations': { results: !noIntegrations ? [mockIntegration] : [] },
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
                        insightShortId={insightShortIdRef.current}
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
                    insightShortId={insightShortIdRef.current}
                    isOpen={modalOpen}
                />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<StoryArgs>

export const Subscriptions_: Story = {}

export const SubscriptionsEmpty: Story = {
    args: { insightShortId: 'empty' as InsightShortId },
}

export const SubscriptionsNew: Story = {
    args: { subscriptionId: 'new' },
}

export const SubscriptionNoIntegrations: Story = {
    args: { subscriptionId: 'new', noIntegrations: true },
}

export const SubscriptionsEdit: Story = {
    args: { subscriptionId: 1 },
}

export const SubscriptionAtAISummaryLimit: Story = {
    args: { subscriptionId: 'new', aiSummaryAtLimit: true },
}

// Freemium gate: a free org under the 5-subscription limit sees the normal create form.
export const SubscriptionsNewFreeUnderLimit: Story = {
    args: { subscriptionId: 'new', freeTierSubscriptionCount: 2 },
}

// Freemium gate: a free org at the limit sees the upgrade paywall instead of the create form.
export const SubscriptionsNewFreeAtLimit: Story = {
    args: { subscriptionId: 'new', freeTierSubscriptionCount: 5 },
}
