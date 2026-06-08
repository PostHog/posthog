import type { Meta, StoryObj } from '@storybook/react'

import { agents, agentsWithArchived, fleetStats, getAgentStatsFixture } from '@posthog/agent-chat/fixtures'

import { AgentsList } from './AgentsList'

const meta: Meta<typeof AgentsList> = {
    title: 'Agent console components/Pages/Agents List',
    component: AgentsList,
    parameters: {
        layout: 'fullscreen',
    },
}

export default meta
type Story = StoryObj<typeof AgentsList>

const onOpenAgent = (slug: string): void => console.info('[mock] openAgent', slug)

function statsBySlug(list: typeof agents): Record<string, ReturnType<typeof getAgentStatsFixture>> {
    return Object.fromEntries(list.map((a) => [a.slug, getAgentStatsFixture(a.id)]))
}

export const Default: Story = {
    args: {
        agents,
        fleetStats,
        statsBySlug: statsBySlug(agents),
        onOpenAgent,
    },
}

export const WithArchived: Story = {
    args: {
        agents: agentsWithArchived,
        fleetStats,
        statsBySlug: statsBySlug(agentsWithArchived),
        onOpenAgent,
    },
}

export const Quiet: Story = {
    args: {
        agents,
        fleetStats: { liveSessionCount: 0, sessions24hCount: 14, spend24hUsd: 1.21, approvalsPendingCount: 0 },
        statsBySlug: Object.fromEntries(
            agents.map((a) => [
                a.slug,
                {
                    liveCount: 0,
                    sessions24hCount: 0,
                    spend24hUsd: 0,
                    lastActivityAt: a.updated_at,
                    failureRate24h: undefined,
                },
            ])
        ),
        onOpenAgent,
    },
}

export const Empty: Story = {
    args: {
        agents: [],
        fleetStats: { liveSessionCount: 0, sessions24hCount: 0, spend24hUsd: 0, approvalsPendingCount: 0 },
        statsBySlug: {},
        onOpenAgent,
    },
}

export const SingleAgent: Story = {
    args: {
        agents: agents.slice(0, 1),
        fleetStats: { liveSessionCount: 1, sessions24hCount: 5, spend24hUsd: 0.31, approvalsPendingCount: 0 },
        statsBySlug: statsBySlug(agents.slice(0, 1)),
        onOpenAgent,
    },
}
