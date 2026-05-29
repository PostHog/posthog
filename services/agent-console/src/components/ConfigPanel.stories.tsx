import type { Meta, StoryObj } from '@storybook/react'

import { weeklyDigestDraftRevision, weeklyDigestLiveRevision } from '@posthog/agent-chat/fixtures'

import { ConfigPanel } from './ConfigPanel'

const meta: Meta<typeof ConfigPanel> = {
    title: 'Agent console components/ConfigPanel',
    component: ConfigPanel,
    parameters: { layout: 'centered' },
    decorators: [
        (Story) => (
            <div className="w-[640px] p-4">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof ConfigPanel>

export const LiveSpec: Story = {
    args: { spec: weeklyDigestLiveRevision.spec },
}

export const DraftSpec: Story = {
    args: { spec: weeklyDigestDraftRevision.spec },
}

export const SlackTrigger: Story = {
    args: {
        spec: {
            model: 'anthropic/claude-haiku-4-5',
            triggers: [{ type: 'slack', config: { trusted_workspaces: ['T01ABC', 'T02DEF'] } }],
            secrets: ['SLACK_BOT_TOKEN'],
            limits: { max_turns: 12, max_tool_calls: 40, max_wall_seconds: 90 },
            auth: { mode: 'public' },
        },
    },
}

export const Webhook: Story = {
    args: {
        spec: {
            model: 'anthropic/claude-haiku-4-5',
            triggers: [{ type: 'webhook', config: { path: '/incidents/triage' } }],
            secrets: ['PAGERDUTY_TOKEN'],
            limits: { max_turns: 15, max_tool_calls: 60, max_wall_seconds: 180 },
            auth: { mode: 'pat' },
        },
    },
}

export const Minimal: Story = {
    args: {
        spec: { model: 'anthropic/claude-haiku-4-5' },
    },
}
