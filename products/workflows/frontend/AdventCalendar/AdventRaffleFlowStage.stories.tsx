import { MOCK_USER_UUID } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { adventCalendarLogic } from './adventCalendarLogic'
import { ADVENT_LAST_DAY, ADVENT_QUESTION_DAYS, ADVENT_QUESTIONS } from './adventContent'
import { AdventRaffleFlowStage } from './AdventRaffleFlowStage'

const DAYS = Array.from({ length: ADVENT_LAST_DAY }, (_, index) => index + 1)
let ticketDays: number[] = []

function seed(openedUntil: number, tickets: number[]): void {
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
    ticketDays = tickets
}

function MountedStage(): JSX.Element {
    useMountedLogic(adventCalendarLogic)
    return <AdventRaffleFlowStage />
}

const meta: Meta<typeof AdventRaffleFlowStage> = {
    title: 'Scenes-App/Workflows/Advent calendar/Raffle on the flow stage',
    component: AdventRaffleFlowStage,
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
                '/api/projects/:team_id/workflow_advent_calendar/results/': () => [
                    200,
                    { questions: [], ticket_days: ticketDays },
                ],
            },
            post: {
                '/api/projects/:team_id/workflow_advent_calendar/open/': async ({ request }) => {
                    const { day } = (await request.json()) as { day: number }
                    return [200, { day, opened_at: new Date().toISOString(), ticket_days: [...ticketDays, day] }]
                },
            },
        }),
        (Story) => (
            <div className="flex flex-col" style={{ width: '100vw', height: '100vh' }}>
                <Story />
            </div>
        ),
    ],
    beforeEach: () => seed(5, [1, 3, 4]),
}

export default meta
type Story = StoryObj<typeof AdventRaffleFlowStage>

export const Midway: Story = {}

export const LastDay: Story = {
    parameters: { mockDate: '2026-12-24 09:00:00' },
    beforeEach: () => seed(ADVENT_LAST_DAY - 1, [1, 3, 4, 8, 12, 19, 23]),
}

export const AfterTheDraw: Story = {
    parameters: { mockDate: '2026-12-26 09:00:00' },
    beforeEach: () => seed(ADVENT_LAST_DAY, [1, 3, 4, 8, 12, 19, 23, 24]),
}

export const Preview: Story = {
    parameters: { mockDate: '2026-11-28 09:00:00', pageUrl: `${urls.workflowsAdventCalendar()}?day=24` },
    beforeEach: () => {
        window.localStorage.removeItem('workflows-advent-calendar-progress')
        ticketDays = []
    },
}
