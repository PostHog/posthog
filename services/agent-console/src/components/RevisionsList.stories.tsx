import type { Meta, StoryFn, StoryObj } from '@storybook/react'

import { weeklyDigest, weeklyDigestRevisions } from '@posthog/agent-chat/fixtures'

import { RevisionsList } from './RevisionsList'

const meta: Meta<typeof RevisionsList> = {
    title: 'Agent console components/RevisionsList',
    component: RevisionsList,
    parameters: { layout: 'centered' },
    decorators: [
        (Story: StoryFn) => (
            <div className="w-[720px]">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof RevisionsList>

const onOpenInConfig = (id: string): void => console.info('[mock] openInConfig', id)

export const Default: Story = {
    args: { agent: weeklyDigest, revisions: weeklyDigestRevisions, onOpenInConfig },
}

export const NoLiveYet: Story = {
    args: {
        agent: { ...weeklyDigest, live_revision: null },
        revisions: weeklyDigestRevisions.filter((r) => r.state === 'draft'),
        onOpenInConfig,
    },
}

export const Empty: Story = {
    args: { agent: weeklyDigest, revisions: [], onOpenInConfig },
}
