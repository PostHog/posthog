import type { Meta, StoryFn, StoryObj } from '@storybook/react'

import {
    getAgentStatsFixture,
    listSessionsForAgentFixture,
    weeklyDigest,
    weeklyDigestLiveRevision,
} from '@posthog/agent-chat/fixtures'

import { AgentOverview } from './AgentOverview'

const meta: Meta<typeof AgentOverview> = {
    title: 'Agent console components/AgentOverview',
    component: AgentOverview,
    parameters: { layout: 'centered' },
    decorators: [
        (Story: StoryFn) => (
            <div className="w-[860px]">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof AgentOverview>

const noop = (): void => undefined

export const Default: Story = {
    args: {
        agent: weeklyDigest,
        liveRevision: weeklyDigestLiveRevision,
        stats: getAgentStatsFixture(weeklyDigest.id),
        recentSessions: listSessionsForAgentFixture(weeklyDigest.id),
        onOpenSession: (id) => console.info('[mock] openSession', id),
        onOpenConfiguration: noop,
        onOpenSessions: noop,
    },
}

export const NoLiveYet: Story = {
    args: {
        agent: { ...weeklyDigest, live_revision: null },
        liveRevision: null,
        stats: getAgentStatsFixture(weeklyDigest.id),
        recentSessions: [],
        onOpenSession: noop,
        onOpenConfiguration: noop,
        onOpenSessions: noop,
    },
}

export const Quiet: Story = {
    args: {
        agent: weeklyDigest,
        liveRevision: weeklyDigestLiveRevision,
        stats: {
            liveCount: 0,
            sessions24hCount: 0,
            spend24hUsd: 0,
            lastActivityAt: undefined,
            failureRate24h: undefined,
        },
        recentSessions: [],
        onOpenSession: noop,
        onOpenConfiguration: noop,
        onOpenSessions: noop,
    },
}
