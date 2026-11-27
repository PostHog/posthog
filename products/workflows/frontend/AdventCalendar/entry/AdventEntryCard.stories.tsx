import { MOCK_USER_UUID } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import { ADVENT_QUESTIONS } from '../adventContent'
import { PROGRESS_STORAGE_KEY } from '../adventProgressStorage'
import { AdventEntryCard } from './AdventEntryCard'

function storeOpenedDoors(count: number): () => void {
    return () => {
        const opened = Array.from({ length: count }, (_, index) => index + 1)
        const answers = Object.fromEntries(
            opened.flatMap((day) => (ADVENT_QUESTIONS[day] ? [[day, ADVENT_QUESTIONS[day].options[0].id]] : []))
        )
        window.localStorage.setItem(PROGRESS_STORAGE_KEY, JSON.stringify({ [MOCK_USER_UUID]: { opened, answers } }))
    }
}

const meta: Meta<typeof AdventEntryCard> = {
    title: 'Scenes-App/Workflows/Advent calendar/Entry card',
    component: AdventEntryCard,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
    args: { phase: { status: 'open', day: 3 } },
    beforeEach: storeOpenedDoors(2),
    decorators: [
        (Story) => (
            <div className="p-4">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof AdventEntryCard>

export const TwoDoorsOpen: Story = {}

export const TwelveDoorsOpen: Story = { args: { phase: { status: 'open', day: 13 } }, beforeEach: storeOpenedDoors(12) }

export const AllDoorsOpen: Story = { args: { phase: { status: 'over' } }, beforeEach: storeOpenedDoors(24) }

export const BeforeDecember: Story = { args: { phase: { status: 'soon' } }, beforeEach: storeOpenedDoors(0) }

export const NarrowScene: Story = {
    decorators: [
        (Story) => (
            <div className="w-[480px]">
                <Story />
            </div>
        ),
    ],
}
