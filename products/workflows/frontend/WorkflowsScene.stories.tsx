import { Meta, StoryFn } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

import { workflowsSceneLogic } from './WorkflowsScene'

const MOCK_HOG_FLOWS = [
    {
        id: 'flow-001',
        team_id: 1,
        version: 1,
        name: 'Welcome email sequence',
        description: 'Sends a welcome email to new sign-ups',
        status: 'active',
        exit_condition: 'exit_only_at_end',
        trigger: { type: 'event', filters: {} },
        actions: [
            {
                id: 'action-1',
                name: 'Send welcome email',
                description: '',
                type: 'function_email',
                config: { template_id: 'template-email', inputs: {} },
            },
        ],
        edges: [{ from: 'trigger', to: 'action-1', type: 'continue' }],
        created_at: '2024-12-01T10:00:00Z',
        updated_at: '2024-12-20T14:30:00Z',
        created_by: { id: 1, first_name: 'Test', email: 'test@posthog.com' },
    },
    {
        id: 'flow-002',
        team_id: 1,
        version: 1,
        name: 'Trial expiry reminder',
        description: 'Notify users when their trial is about to expire',
        status: 'draft',
        exit_condition: 'exit_only_at_end',
        trigger: { type: 'event', filters: {} },
        actions: [
            {
                id: 'action-2',
                name: 'Send SMS reminder',
                description: '',
                type: 'function_sms',
                config: { template_id: 'template-twilio', inputs: {} },
            },
        ],
        edges: [{ from: 'trigger', to: 'action-2', type: 'continue' }],
        created_at: '2025-01-10T09:00:00Z',
        updated_at: '2025-01-10T09:00:00Z',
        created_by: { id: 1, first_name: 'Test', email: 'test@posthog.com' },
    },
    {
        id: 'flow-003',
        team_id: 1,
        version: 1,
        name: 'Feature adoption nudge',
        description: 'Notify when users have not tried key features',
        status: 'active',
        exit_condition: 'exit_only_at_end',
        trigger: { type: 'event', filters: {} },
        actions: [
            {
                id: 'action-3',
                name: 'Post to webhook',
                description: '',
                type: 'function',
                config: { template_id: 'template-webhook', inputs: {} },
            },
        ],
        edges: [{ from: 'trigger', to: 'action-3', type: 'continue' }],
        created_at: '2025-01-05T11:00:00Z',
        updated_at: '2025-01-15T16:00:00Z',
        created_by: { id: 1, first_name: 'Test', email: 'test@posthog.com' },
    },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Workflows',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.workflows(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/hog_flows/': toPaginatedResponse(MOCK_HOG_FLOWS),
                '/api/environments/:team_id/messaging_templates/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
}
export default meta

export const WorkflowsList: StoryFn = () => {
    return <App />
}
WorkflowsList.parameters = { pageUrl: urls.workflows() }

export const WorkflowsListEmpty: StoryFn = () => {
    return <App />
}
WorkflowsListEmpty.parameters = { pageUrl: urls.workflows() }
WorkflowsListEmpty.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/hog_flows/': EMPTY_PAGINATED_RESPONSE,
            '/api/environments/:team_id/messaging_templates/': EMPTY_PAGINATED_RESPONSE,
        },
    }),
]

export const WorkflowsLibraryTab: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        workflowsSceneLogic().mount()
        workflowsSceneLogic().actions.setCurrentTab('library')
    })
    return <App />
}
WorkflowsLibraryTab.parameters = { pageUrl: urls.workflows('library') }
