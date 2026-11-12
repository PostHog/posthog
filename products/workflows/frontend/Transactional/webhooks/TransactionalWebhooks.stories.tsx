import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { useStorybookMocks } from '~/mocks/browser'

import { DELIVERY_WEBHOOK_LIST_FILTER_GROUPS } from './deliveryWebhookPayload'
import { deliveryWebhooksLogic } from './deliveryWebhooksLogic'
import { TransactionalWebhooks } from './TransactionalWebhooks'

const webhook = {
    id: '019b0000-0000-7000-8000-000000000001',
    type: 'destination',
    name: 'Transactional email webhook: api.example.com',
    description: 'Sends delivery updates for transactional emails to your endpoint.',
    enabled: true,
    deleted: false,
    hog: '',
    bytecode: [],
    inputs_schema: [],
    inputs: { url: { value: 'https://api.example.com/webhooks/email' } },
    filters: {
        events: [{ id: '$workflows_email_delivered', type: 'events' }],
        ...DELIVERY_WEBHOOK_LIST_FILTER_GROUPS[0],
    },
    icon_url: '/static/services/webhook.svg',
    template: { id: 'template-webhook', name: 'HTTP Webhook' },
    status: { state: 1, ratings: [], states: [] },
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    created_by: { id: 1, uuid: 'user-001', distinct_id: 'user-001', first_name: 'Test', email: 'test@posthog.com' },
}

const meta: Meta = {
    title: 'Products/Workflows/TransactionalWebhooks',
    component: TransactionalWebhooks,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<{ engagementEvents: boolean; addOpen?: boolean }>

function WebhooksStory({ engagementEvents, addOpen }: { engagementEvents: boolean; addOpen?: boolean }): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/hog_functions/': {
                count: engagementEvents ? 1 : 0,
                results: engagementEvents ? [webhook] : [],
                next: null,
            },
        },
    })
    const { loadCurrentTeamSuccess } = useActions(teamLogic)
    const { openAddModal } = useActions(deliveryWebhooksLogic)
    useEffect(() => {
        loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            workflows_config: {
                ...MOCK_DEFAULT_TEAM.workflows_config,
                capture_workflows_engagement_events: engagementEvents,
            },
        })
        if (addOpen) {
            openAddModal()
        }
    }, [engagementEvents, addOpen, loadCurrentTeamSuccess, openAddModal])
    return (
        <div className="max-w-[520px]">
            <TransactionalWebhooks />
        </div>
    )
}

export const EngagementEventsOff: Story = {
    render: () => <WebhooksStory engagementEvents={false} />,
}

export const WithWebhook: Story = {
    render: () => <WebhooksStory engagementEvents />,
}

export const AddWebhook: Story = {
    render: () => <WebhooksStory engagementEvents addOpen />,
}
