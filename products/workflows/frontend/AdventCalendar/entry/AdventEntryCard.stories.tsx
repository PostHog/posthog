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
        mockDate: '2026-12-03 09:00:00',
        testOptions: { snapshotBrowsers: [] },
    },
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

export const TwelveDoorsOpen: Story = {
    parameters: { mockDate: '2026-12-13 09:00:00' },
    beforeEach: storeOpenedDoors(12),
}

export const AllDoorsOpen: Story = { parameters: { mockDate: '2026-12-26 09:00:00' }, beforeEach: storeOpenedDoors(24) }

export const BeforeDecember: Story = {
    parameters: { mockDate: '2026-11-27 09:00:00' },
    beforeEach: storeOpenedDoors(0),
}

export const NarrowScene: Story = {
    decorators: [
        (Story) => (
            <div className="w-[480px]">
                <Story />
            </div>
        ),
    ],
}
