import type { Meta, StoryFn, StoryObj } from '@storybook/react'

import { fleetLiveSessions } from '@posthog/agent-chat/fixtures'

import { LiveNowPanel } from './LiveNowPanel'

const meta: Meta<typeof LiveNowPanel> = {
    title: 'Agent console components/LiveNowPanel',
    component: LiveNowPanel,
    parameters: { layout: 'centered' },
    decorators: [
        (Story: StoryFn) => (
            <div className="h-[420px] w-[320px]">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof LiveNowPanel>

const onOpenSession = (id: string): void => console.info('[mock] openSession', id)
const onOpenAgent = (slug: string): void => console.info('[mock] openAgent', slug)
const onViewAll = (): void => console.info('[mock] viewAllSessions')

export const Default: Story = {
    args: {
        sessions: fleetLiveSessions,
        onOpenSession,
        onOpenAgent,
        onViewAll,
    },
}

export const Empty: Story = {
    args: {
        sessions: [],
        onOpenSession,
        onOpenAgent,
        onViewAll,
    },
}

export const SingleSession: Story = {
    args: {
        sessions: fleetLiveSessions.slice(0, 1),
        onOpenSession,
        onOpenAgent,
        onViewAll,
    },
}

export const ManySessions: Story = {
    args: {
        sessions: [...fleetLiveSessions, ...fleetLiveSessions.map((s, i) => ({ ...s, id: `${s.id}-dup-${i}` }))],
        limit: 10,
        onOpenSession,
        onOpenAgent,
        onViewAll,
    },
}
