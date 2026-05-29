import type { Meta, StoryObj } from '@storybook/react'

import {
    getAgentStatsFixture,
    listSessionsForAgentFixture,
    weeklyDigest,
    weeklyDigestBundle,
    weeklyDigestRevisions,
} from '@posthog/agent-chat/fixtures'

import { AgentDetail } from './AgentDetail'

const meta: Meta<typeof AgentDetail> = {
    title: 'Agent console components/Pages/Agent Detail',
    component: AgentDetail,
    parameters: {
        layout: 'fullscreen',
    },
}

export default meta
type Story = StoryObj<typeof AgentDetail>

const onTryAgent = (): void => console.info('[mock] tryAgent')
const onOpenSession = (id: string): void => console.info('[mock] openSession', id)

const sharedArgs = {
    agent: weeklyDigest,
    revisions: weeklyDigestRevisions,
    bundle: weeklyDigestBundle,
    stats: getAgentStatsFixture(weeklyDigest.id),
    sessions: listSessionsForAgentFixture(weeklyDigest.id),
    onTryAgent,
    onOpenSession,
}

export const Overview: Story = {
    args: sharedArgs,
}

export const NoLiveYet: Story = {
    args: {
        ...sharedArgs,
        agent: { ...weeklyDigest, live_revision: null },
        revisions: weeklyDigestRevisions.filter((r) => r.state === 'draft'),
    },
}

export const QuietAgent: Story = {
    args: {
        ...sharedArgs,
        sessions: [],
        stats: {
            liveCount: 0,
            sessions24hCount: 0,
            spend24hUsd: 0,
            lastActivityAt: undefined,
            failureRate24h: undefined,
        },
    },
}

export const EmptyBundle: Story = {
    args: {
        ...sharedArgs,
        bundle: [],
    },
}
