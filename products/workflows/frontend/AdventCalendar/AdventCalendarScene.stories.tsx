import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { expect, userEvent } from 'storybook/test'

import { AdventCalendarScene } from './AdventCalendarScene'

const meta: Meta<typeof AdventCalendarScene> = {
    title: 'Scenes-App/Workflows/Advent calendar',
    component: AdventCalendarScene,
    parameters: {
        layout: 'fullscreen',
        pageUrl: urls.workflowsAdventCalendar(),
        mockDate: '2026-12-03 09:00:00',
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR],
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        (Story) => (
            <div className="flex h-[720px] w-[1200px] flex-col">
                <Story />
            </div>
        ),
    ],
    beforeEach: () => {
        window.localStorage.removeItem('workflows-advent-calendar-progress')
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('A very merry PostHog')
        await expect(canvas.queryByRole('button', { name: 'Share' })).toBeNull()
        await waitFor(() => expect(userLogic.findMounted()?.values.user?.uuid).toBeTruthy())

        await userEvent.click(await canvas.findByRole('button', { name: 'Door 1, ready' }))

        await canvas.findByRole('button', { name: 'Share' })
    },
}

export default meta
type Story = StoryObj<typeof AdventCalendarScene>

export const ThirdOfDecember: Story = {}
