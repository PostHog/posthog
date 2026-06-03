import type { Meta, StoryFn, StoryObj } from '@storybook/react'

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
        (Story: StoryFn) => (
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
