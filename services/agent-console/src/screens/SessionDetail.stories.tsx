import type { Meta, StoryObj } from '@storybook/react'

import {
    listLogsForSessionFixture,
    listSessionsForAgentFixture,
    releaseConcierge,
    weeklyDigest,
} from '@posthog/agent-chat/fixtures'

import { SessionDetail } from './SessionDetail'

const meta: Meta<typeof SessionDetail> = {
    title: 'Agent console components/Pages/Session Detail',
    component: SessionDetail,
    parameters: { layout: 'fullscreen' },
    decorators: [
        (Story) => (
            <div className="h-screen">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof SessionDetail>

const digestHistory = listSessionsForAgentFixture(weeklyDigest.id)
const releaseHistory = listSessionsForAgentFixture(releaseConcierge.id)

const chatTestRun = digestHistory.find((s) => s.id.endsWith('07d2'))!
const failedRun = digestHistory.find((s) => s.id.endsWith('07d3'))!
const slackQuestion = releaseHistory.find((s) => s.id.endsWith('07e2'))!
const cronFire = digestHistory.find((s) => s.id.endsWith('07d1'))!

const noop = (): void => undefined

export const ChatTestRun: Story = {
    args: {
        session: chatTestRun,
        logs: listLogsForSessionFixture(chatTestRun.id),
        onClose: noop,
    },
}

export const SlackThread: Story = {
    args: {
        session: slackQuestion,
        logs: listLogsForSessionFixture(slackQuestion.id),
        onClose: noop,
    },
}

export const CronFire: Story = {
    args: {
        session: cronFire,
        logs: listLogsForSessionFixture(cronFire.id),
        onClose: noop,
    },
}

export const FailedSession: Story = {
    args: {
        session: failedRun,
        logs: listLogsForSessionFixture(failedRun.id),
        onClose: noop,
    },
}

// Pins how the failure banner renders when the runner stamps a
// long, scrubbed error onto a crashed session. The error text mirrors
// what `truncateFailureReason` (services/agent-runner/src/workers/worker.ts)
// produces: token shape redacted, multi-line collapsed, terminal
// ellipsis if over 512 chars. The "View logs" button switches the
// inner Tabs to the Logs pane so the operator can see the raw stack.
export const FailedSessionWithLongReason: Story = {
    args: {
        session: {
            ...failedRun,
            error: 'MCP open failed: github: Streamable HTTP error: bad request: error: Authorization: Bearer ghp_**** rejected. The Copilot license for this organization does not allow Streamable HTTP transports for personal access tokens; check the integration settings or fall back to the `@posthog/http-request` tool with a manual Authorization header.',
        },
        logs: listLogsForSessionFixture(failedRun.id),
        onClose: noop,
    },
}
