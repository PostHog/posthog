import { MOCK_USER_UUID } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import { useMountedLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect } from 'storybook/test'

import { adventCalendarLogic } from '../adventCalendarLogic'
import { ADVENT_LAST_DAY, ADVENT_QUESTION_DAYS, ADVENT_QUESTIONS } from '../adventContent'
import { AdventFlowStage } from './AdventFlowStage'

const DAYS = Array.from({ length: ADVENT_LAST_DAY }, (_, index) => index + 1)

function seed(openedUntil: number): void {
    const opened = DAYS.slice(0, openedUntil)
    const answers = Object.fromEntries(
        ADVENT_QUESTION_DAYS.filter((day) => day <= openedUntil).map((day) => [
            day,
            ADVENT_QUESTIONS[day].options[day % 2].id,
        ])
    )
    window.localStorage.setItem(
        'workflows-advent-calendar-progress',
        JSON.stringify({ [MOCK_USER_UUID]: { opened, answers } })
    )
}

function MountedStage(): JSX.Element {
    useMountedLogic(adventCalendarLogic)
    return <AdventFlowStage />
}

const meta: Meta<typeof AdventFlowStage> = {
    title: 'Scenes-App/Workflows/Advent calendar/Flow stage',
    component: AdventFlowStage,
    render: () => <MountedStage />,
    parameters: {
        layout: 'fullscreen',
        pageUrl: urls.workflowsAdventCalendar(),
        mockDate: '2026-12-06 09:00:00',
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR],
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/workflow_advent_calendar/results/': {
                    questions: [
                        {
                            day: 2,
                            answer: ADVENT_QUESTIONS[2].options[0].id,
                            shares: ADVENT_QUESTIONS[2].options.map((option, index) => ({
                                option: option.id,
                                share: index === 0 ? 38 : 62,
                            })),
                        },
                    ],
                },
            },
        }),
        (Story) => (
            <div className="flex flex-col" style={{ width: 1200, height: 760 }}>
                <Story />
            </div>
        ),
    ],
    beforeEach: () => seed(5),
    play: async ({ canvasElement }) => {
        await expect(await within(canvasElement).findByRole('button', { name: /^Door 1, open/ })).toBeTruthy()
    },
}

export default meta
type Story = StoryObj<typeof AdventFlowStage>

export const Midway: Story = {}

export const EveryDoorOpen: Story = {
    parameters: { mockDate: '2026-12-24 09:00:00' },
    beforeEach: () => seed(ADVENT_LAST_DAY),
}

export const Phone: Story = {
    decorators: [
        (Story) => (
            <div className="flex flex-col" style={{ width: 375, height: 700 }}>
                <Story />
            </div>
        ),
    ],
}
