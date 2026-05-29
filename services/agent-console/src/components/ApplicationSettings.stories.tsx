import type { Meta, StoryObj } from '@storybook/react'

import { weeklyDigest, weeklyDigestDraftRevision, weeklyDigestLiveRevision } from '@posthog/agent-chat/fixtures'

import { ApplicationSettings } from './ApplicationSettings'

const meta: Meta<typeof ApplicationSettings> = {
    title: 'Agent console components/ApplicationSettings',
    component: ApplicationSettings,
    parameters: { layout: 'centered' },
    decorators: [
        (Story) => (
            <div className="w-[720px]">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof ApplicationSettings>

export const Default: Story = {
    args: { agent: weeklyDigest, referenceRevision: weeklyDigestLiveRevision },
}

export const WithDeclaredSecrets: Story = {
    args: { agent: weeklyDigest, referenceRevision: weeklyDigestDraftRevision },
}

export const NoRevisionYet: Story = {
    args: { agent: { ...weeklyDigest, live_revision: null }, referenceRevision: null },
}

export const Archived: Story = {
    args: {
        agent: { ...weeklyDigest, archived: true, archived_at: '2026-04-01T10:00:00Z' },
        referenceRevision: weeklyDigestLiveRevision,
    },
}
