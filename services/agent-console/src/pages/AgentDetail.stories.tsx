import type { Meta, StoryObj } from '@storybook/react'

import {
    getAgentStatsFixture,
    listLogsForSessionFixture,
    listSessionsForAgentFixture,
    weeklyDigest,
    weeklyDigestRevisions,
} from '@posthog/agent-chat/fixtures'

import { AgentDetail, type AgentDetailUrlState } from './AgentDetail'

const meta: Meta<typeof AgentDetail> = {
    title: 'Agent console components/Pages/Agent Detail',
    component: AgentDetail,
    parameters: {
        layout: 'fullscreen',
    },
    decorators: [
        (Story) => (
            <div className="h-screen">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof AgentDetail>

const onTryAgent = (): void => console.info('[mock] tryAgent')
const onOpenSession = (id: string): void => console.info('[mock] openSession', id)
const onChangeUrlState = (next: Partial<AgentDetailUrlState>): void => console.info('[mock] urlState ←', next)

const overviewUrlState: AgentDetailUrlState = {
    tab: 'overview',
    revisionId: weeklyDigest.live_revision,
    section: null,
    filePath: null,
    editSecret: null,
    callbackSessionId: null,
    selectedSessionId: null,
}

const weeklyDigestSessions = listSessionsForAgentFixture(weeklyDigest.id)
const firstSession = weeklyDigestSessions[0]

const sharedArgs = {
    agent: weeklyDigest,
    revisions: weeklyDigestRevisions,
    stats: getAgentStatsFixture(weeklyDigest.id),
    sessions: weeklyDigestSessions,
    selectedSession: null,
    selectedSessionLogs: [],
    selectedSessionLoading: false,
    urlState: overviewUrlState,
    onChangeUrlState,
    onTryAgent,
    onOpenSession,
}

export const Overview: Story = {
    args: sharedArgs,
}

export const Configuration: Story = {
    args: {
        ...sharedArgs,
        urlState: { ...overviewUrlState, tab: 'configuration' },
    },
}

export const Sessions: Story = {
    args: {
        ...sharedArgs,
        urlState: { ...overviewUrlState, tab: 'sessions' },
    },
}

export const SessionsWithSelection: Story = {
    args: {
        ...sharedArgs,
        urlState: {
            ...overviewUrlState,
            tab: 'sessions',
            selectedSessionId: firstSession?.id ?? null,
        },
        selectedSession: firstSession ?? null,
        selectedSessionLogs: firstSession ? listLogsForSessionFixture(firstSession.id) : [],
    },
}

export const Memory: Story = {
    args: {
        ...sharedArgs,
        urlState: { ...overviewUrlState, tab: 'memory' },
    },
}

export const NoLiveYet: Story = {
    args: {
        ...sharedArgs,
        agent: { ...weeklyDigest, live_revision: null },
        revisions: weeklyDigestRevisions.filter((r) => r.state === 'draft'),
        urlState: { ...overviewUrlState, revisionId: null },
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
