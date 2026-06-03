import type { Meta, StoryFn, StoryObj } from '@storybook/react'

import {
    listSessionsForAgentFixture,
    playgroundSession,
    releaseConcierge,
    weeklyDigest,
} from '@posthog/agent-chat/fixtures'

import { SessionPlayback } from './SessionPlayback'

const meta: Meta<typeof SessionPlayback> = {
    title: 'Agent console components/SessionPlayback',
    component: SessionPlayback,
    parameters: { layout: 'centered' },
    decorators: [
        (Story: StoryFn) => (
            <div className="h-[600px] w-[700px]">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof SessionPlayback>

const digestHistory = listSessionsForAgentFixture(weeklyDigest.id)
const releaseHistory = listSessionsForAgentFixture(releaseConcierge.id)

const chatTestRun = digestHistory.find((s) => s.id.endsWith('07d2'))!
const cronFire = digestHistory.find((s) => s.id.endsWith('07d1'))!
const slackQuestion = releaseHistory.find((s) => s.id.endsWith('07e2'))!
const failedRun = digestHistory.find((s) => s.id.endsWith('07d3'))!

export const ChatTrigger: Story = {
    args: { session: chatTestRun },
}

export const SlackTrigger: Story = {
    args: { session: slackQuestion },
}

export const CronTrigger: Story = {
    args: { session: cronFire },
}

export const PlaygroundChat: Story = {
    args: { session: playgroundSession },
}

export const FailedChatRun: Story = {
    args: { session: failedRun },
}
