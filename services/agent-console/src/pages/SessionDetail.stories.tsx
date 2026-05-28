import type { Meta, StoryObj } from '@storybook/react'

import {
    listLogsForSessionFixture,
    listSessionsForAgentFixture,
    releaseConcierge,
    weeklyDigest,
} from '@posthog/agent-chat/fixtures'

import { SessionDetail } from './SessionDetail'

const meta: Meta<typeof SessionDetail> = {
    title: 'Console/Pages/Session Detail',
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
        agent: weeklyDigest,
        session: chatTestRun,
        logs: listLogsForSessionFixture(chatTestRun.id),
        onBackToList: noop,
        onBackToAgent: noop,
    },
}

export const SlackThread: Story = {
    args: {
        agent: releaseConcierge,
        session: slackQuestion,
        logs: listLogsForSessionFixture(slackQuestion.id),
        onBackToList: noop,
        onBackToAgent: noop,
    },
}

export const CronFire: Story = {
    args: {
        agent: weeklyDigest,
        session: cronFire,
        logs: listLogsForSessionFixture(cronFire.id),
        onBackToList: noop,
        onBackToAgent: noop,
    },
}

export const FailedSession: Story = {
    args: {
        agent: weeklyDigest,
        session: failedRun,
        logs: listLogsForSessionFixture(failedRun.id),
        onBackToList: noop,
        onBackToAgent: noop,
    },
}
