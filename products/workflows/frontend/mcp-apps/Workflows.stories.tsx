import { McpThemeDecorator } from '@common/mosaic/storybook/decorator'
import type { Meta, StoryFn } from '@storybook/react'

import { WorkflowListView, type WorkflowData, type WorkflowListData, WorkflowView } from './index'

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

export const Active: StoryFn = () => <WorkflowView workflow={activeWorkflow} />
Active.storyName = 'Active workflow'

export const DraftState: StoryFn = () => <WorkflowView workflow={draftWorkflow} />
DraftState.storyName = 'Draft workflow'

export const Archived: StoryFn = () => <WorkflowView workflow={archivedWorkflow} />
Archived.storyName = 'Archived workflow'

const sampleListData: WorkflowListData = {
    count: 3,
    results: [activeWorkflow, draftWorkflow, archivedWorkflow],
    _posthogUrl: 'https://us.posthog.com/project/1/pipeline/destinations',
}

export const List: StoryFn = () => <WorkflowListView data={sampleListData} />
List.storyName = 'Workflow list'
