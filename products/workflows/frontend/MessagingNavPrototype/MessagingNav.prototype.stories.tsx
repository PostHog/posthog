// PROTOTYPE, never merged: PostHog/michaelr-context#419. Round 1: three ways into Email & Messaging, in the
// today-rail-nav shell. Open a story, then flip variants with the bar at the bottom or the arrow keys.
import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'

import {
    MessagingNavVariant,
    messagingNavPrototypeLogic,
} from '~/layout/today/messagingNavPrototype/messagingNavPrototypeLogic'
import { MessagingNavPrototypeSwitcher } from '~/layout/today/messagingNavPrototype/MessagingNavPrototypeSwitcher'
import { mswDecorator } from '~/mocks/browser'

import { PROTOTYPE_WORKFLOWS } from './prototypeData'

const ACTION_TYPES: Record<string, string> = {
    Email: 'function_email',
    SMS: 'function_sms',
    Push: 'function_push',
    Slack: 'function',
    Webhook: 'function',
    'Update person': 'function',
}

const HOG_FLOWS = PROTOTYPE_WORKFLOWS.map((w, index) => ({
    id: `0190f0f0-0000-7000-8000-00000000000${index}`,
    name: w.name,
    description: '',
    version: 1,
    status: w.status === 'Live' ? 'active' : w.status === 'Draft' ? 'draft' : 'archived',
    origin_product: w.kind === 'Loop' ? 'loops' : null,
    trigger: { type: 'event', filters: {} },
    actions: [
        { id: 'trigger_node', type: 'trigger', name: 'Trigger', config: { type: 'event', filters: {} } },
        ...w.channels.map((channel, i) => ({
            id: `action_${i}`,
            type: ACTION_TYPES[channel],
            name: channel,
            config: { template_id: `template-${channel.toLowerCase().replace(' ', '-')}`, inputs: {} },
        })),
        { id: 'exit_node', type: 'exit', name: 'Exit', config: { reason: 'Default exit' } },
    ],
    edges: [],
    tags: [],
    created_by: { id: 1, uuid: 'user-1', first_name: 'Alex', email: 'alex@example.com' },
    created_at: '2026-10-01T09:00:00Z',
    updated_at: '2026-11-10T09:00:00Z',
    user_access_level: 'editor',
    kind: w.kind,
}))

function hogFlowsFor(url: URL): { count: number; results: typeof HOG_FLOWS } {
    const types = (url.searchParams.get('type') ?? '').split(',').filter(Boolean)
    const results = types.length
        ? HOG_FLOWS.filter((flow) => types.includes(flow.kind.toLowerCase()))
        : HOG_FLOWS.filter((flow) => flow.status !== 'archived')
    return { count: results.length, results }
}

let appliedForStory: string | null = null

const meta: Meta = {
    component: App,
    title: 'Prototypes/Email & Messaging navigation',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/': ({ request }) => hogFlowsFor(new URL(request.url)),
                '/api/projects/:team_id/hog_flows/email_sending_suspension/': { suspended: false },
                '/api/projects/:team_id/hog_flow_templates/': { count: 0, results: [] },
                '/api/projects/:team_id/messaging_categories/': { count: 0, results: [] },
                '/api/projects/:team_id/messaging_templates/': { count: 0, results: [] },
                '/api/projects/:team_id/health_issues/summary/': {},
            },
            post: {
                '/api/projects/:team_id/file_system/home_folder/': { id: 'home-folder', path: 'Users/Alex Example' },
            },
        }),
        (Story, { id, parameters }) => {
            // The shell reads the variant while it maps the first URL to a pane, so it is set before the first render.
            // Once per story, so a later render never undoes a switch made with the bar.
            messagingNavPrototypeLogic.mount()
            if (appliedForStory !== id) {
                appliedForStory = id
                messagingNavPrototypeLogic.actions.setVariant(parameters.variant as MessagingNavVariant)
            }
            return (
                <>
                    <Story />
                    <MessagingNavPrototypeSwitcher />
                </>
            )
        },
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-11-19 10:00:00',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API],
    },
}
export default meta

type Story = StoryObj

export const VariantA: Story = {
    parameters: { variant: 'A', pageUrl: '/messaging/broadcasts?variant=A' },
}
export const VariantB: Story = {
    parameters: { variant: 'B', pageUrl: '/messaging/broadcasts?variant=B' },
}
export const VariantC: Story = {
    parameters: { variant: 'C', pageUrl: '/messaging/broadcasts?variant=C' },
}
export const WorkflowsAfterTheMove: Story = {
    parameters: { variant: 'B', pageUrl: '/workflows?variant=B' },
}
