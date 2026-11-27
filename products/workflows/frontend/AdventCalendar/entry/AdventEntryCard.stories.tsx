import type { Meta, StoryObj } from '@storybook/react'

import { AdventEntryCard } from './AdventEntryCard'

const meta: Meta<typeof AdventEntryCard> = {
    title: 'Scenes-App/Workflows/Advent calendar/Entry card',
    component: AdventEntryCard,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
    args: { phase: { status: 'open', day: 3 } },
    decorators: [
        (Story) => (
            <div className="w-[960px] p-4">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof AdventEntryCard>

export const DoorOpen: Story = {}

export const BeforeDecember: Story = { args: { phase: { status: 'soon' } } }

export const AllDoorsOpen: Story = { args: { phase: { status: 'over' } } }

export const NarrowScene: Story = {
    decorators: [
        (Story) => (
            <div className="w-[480px] p-4">
                <Story />
            </div>
        ),
    ],
}
