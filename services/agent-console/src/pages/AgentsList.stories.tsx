import type { Meta, StoryObj } from '@storybook/react'

import {
    agents,
    agentsWithArchived,
    fleetLiveSessions,
    fleetStats,
    liveSessionCountsByAgent,
} from '@posthog/agent-chat/fixtures'

import { AgentsList } from './AgentsList'

const meta: Meta<typeof AgentsList> = {
    title: 'Console/Pages/Agents List',
    component: AgentsList,
    parameters: {
        layout: 'fullscreen',
    },
}

export default meta
type Story = StoryObj<typeof AgentsList>

const onOpenAgent = (slug: string): void => console.info('[mock] openAgent', slug)
const onCreateAgent = (): void => console.info('[mock] createAgent')
const onOpenSession = (id: string): void => console.info('[mock] openSession', id)
const onViewAllSessions = (): void => console.info('[mock] viewAllSessions')

export const Default: Story = {
    args: {
        agents,
        fleetStats,
        liveSessions: fleetLiveSessions,
        liveCountByAgent: liveSessionCountsByAgent,
        onOpenAgent,
        onCreateAgent,
        onOpenSession,
        onViewAllSessions,
    },
}

export const WithArchived: Story = {
    args: {
        agents: agentsWithArchived,
        fleetStats,
        liveSessions: fleetLiveSessions,
        liveCountByAgent: liveSessionCountsByAgent,
        onOpenAgent,
        onCreateAgent,
        onOpenSession,
        onViewAllSessions,
    },
}

export const Quiet: Story = {
    args: {
        agents,
        fleetStats: { liveSessionCount: 0, sessions24hCount: 14, spend24hUsd: 1.21, approvalsPendingCount: 0 },
        liveSessions: [],
        liveCountByAgent: {},
        onOpenAgent,
        onCreateAgent,
        onOpenSession,
        onViewAllSessions,
    },
}

export const Empty: Story = {
    args: {
        agents: [],
        fleetStats: { liveSessionCount: 0, sessions24hCount: 0, spend24hUsd: 0, approvalsPendingCount: 0 },
        liveSessions: [],
        liveCountByAgent: {},
        onOpenAgent,
        onCreateAgent,
        onOpenSession,
        onViewAllSessions,
    },
}

export const SingleAgent: Story = {
    args: {
        agents: agents.slice(0, 1),
        fleetStats: { liveSessionCount: 1, sessions24hCount: 5, spend24hUsd: 0.31, approvalsPendingCount: 0 },
        liveSessions: fleetLiveSessions.slice(0, 1),
        liveCountByAgent: { [agents[0].id]: 1 },
        onOpenAgent,
        onCreateAgent,
        onOpenSession,
        onViewAllSessions,
    },
}
