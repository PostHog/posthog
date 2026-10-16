import type { Meta, StoryObj } from '@storybook/react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import {
    WorkflowDataSuggestionsView,
    type WorkflowDataSuggestionsData,
    WorkflowListView,
    type WorkflowData,
    type WorkflowListData,
    WorkflowView,
} from './index'

const meta: Meta = {
    title: 'MCP Apps/Workflows',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            // McpThemeDecorator doesn't have dark mode built-in by default so just disable this to avoid duplicated snapshots
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

const activeWorkflow: WorkflowData = {
    id: 'wf-1',
    name: 'Onboarding email sequence',
    description: 'Sends a series of onboarding emails to new signups over 7 days.',
    status: 'active',
    version: 3,
    exit_condition: 'completed_onboarding',
    created_at: '2025-09-15T09:00:00Z',
    updated_at: '2025-12-01T14:00:00Z',
    created_by: { first_name: 'Jane', email: 'jane@posthog.com' },
    _posthogUrl: 'https://us.posthog.com/project/1/pipeline/destinations/wf-1',
}

const draftWorkflow: WorkflowData = {
    id: 'wf-2',
    name: 'Re-engagement campaign',
    description: 'Trigger push notifications for users inactive for 14 days.',
    status: 'draft',
    version: 1,
    created_at: '2025-12-10T09:00:00Z',
    updated_at: '2025-12-10T09:00:00Z',
}

const archivedWorkflow: WorkflowData = {
    id: 'wf-3',
    name: 'Legacy welcome flow',
    status: 'archived',
    version: 5,
    exit_condition: 'first_event_sent',
    created_at: '2025-06-01T09:00:00Z',
    updated_at: '2025-11-01T09:00:00Z',
    created_by: { first_name: 'Alex' },
}

export const Active: Story = {
    render: () => <WorkflowView workflow={activeWorkflow} />,
    name: 'Active workflow',
}

export const DraftState: Story = {
    render: () => <WorkflowView workflow={draftWorkflow} />,
    name: 'Draft workflow',
}

export const Archived: Story = {
    render: () => <WorkflowView workflow={archivedWorkflow} />,
    name: 'Archived workflow',
}

const sampleListData: WorkflowListData = {
    count: 3,
    results: [activeWorkflow, draftWorkflow, archivedWorkflow],
    _posthogUrl: 'https://us.posthog.com/project/1/pipeline/destinations',
}

export const List: Story = {
    render: () => <WorkflowListView data={sampleListData} />,
    name: 'Workflow list',
}

const suggestionsData: WorkflowDataSuggestionsData = {
    status: 'ready',
    email_sender_ready: true,
    suggestions: [
        {
            id: 'suggestion-1',
            name: 'Welcome new sign-ups',
            description: 'Send a welcome email, then a few tips if they have not finished onboarding.',
            reason: 'People who just signed up are most open to guidance.',
            trigger_event: 'user_signed_up',
            weekly_count: 57,
        },
        {
            id: 'suggestion-2',
            name: 'Help after failed queries',
            description: 'Send troubleshooting tips when a query fails for someone.',
            reason: 'A quick hand after a failure keeps people from giving up.',
            trigger_event: 'query_failed',
            weekly_count: 21,
        },
        {
            id: 'suggestion-3',
            name: 'Next steps after onboarding',
            description: 'Point people to inviting teammates and building a first dashboard.',
            reason: 'People who finish onboarding are ready for the next feature.',
            trigger_event: 'onboarding_completed',
            weekly_count: 29,
        },
    ],
}

export const DataSuggestions: Story = {
    render: () => <WorkflowDataSuggestionsView data={suggestionsData} builds={{}} onCreate={() => {}} />,
    name: 'Data suggestions',
}

export const DataSuggestionsBuilt: Story = {
    render: () => (
        <WorkflowDataSuggestionsView
            data={{ ...suggestionsData, email_sender_ready: false }}
            builds={{
                'suggestion-1': {
                    status: 'ready',
                    editorUrl: 'https://us.posthog.com/project/1/workflows/wf-9/workflow',
                    missingInputs: [
                        { step_name: 'Welcome aboard', field: 'Email sender' },
                        { step_name: 'A few tips to get started', field: 'Email sender' },
                    ],
                },
                'suggestion-2': {
                    status: 'failed',
                    error: "We couldn't build this workflow. Try again, or pick another suggestion.",
                },
            }}
            onCreate={() => {}}
        />
    ),
    name: 'Data suggestions after a build',
}
