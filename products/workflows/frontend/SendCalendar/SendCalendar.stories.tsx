import { Meta, StoryFn } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'

import type {
    HogFlowBatchJobApi,
    HogFlowMinimalApi,
    HogFlowScheduleApi,
    UserBasicApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { SendCalendar } from './SendCalendar'
import { sendCalendarLogic } from './sendCalendarLogic'

const meta: Meta<typeof SendCalendar> = {
    title: 'Products/Workflows/Send calendar',
    component: SendCalendar,
    parameters: {
        layout: 'padded',
        mockDate: '2026-10-16 12:00:00',
        testOptions: { waitForLoadersToDisappear: true, waitForSelector: '[data-attr=send-calendar-month]' },
    },
}
export default meta

const person = (id: number, first_name: string): UserBasicApi =>
    ({
        id,
        uuid: `0199e0aa-0000-7000-8000-00000000010${id}`,
        first_name,
        email: `${first_name}@example.com`,
    }) as UserBasicApi

const PRIYA = person(1, 'Priya')
const SAM = person(2, 'Sam')

const flowId = (n: number): string => `0199e0aa-0000-7000-8000-0000000000${String(n).padStart(2, '0')}`

const flow = (
    n: number,
    name: string,
    origin_product: 'broadcasts' | null,
    trigger: 'batch' | 'schedule',
    created_by: UserBasicApi
): HogFlowMinimalApi =>
    ({
        id: flowId(n),
        name,
        description: '',
        status: 'active',
        origin_product,
        created_by,
        trigger: { type: trigger },
        actions: [
            { id: 'trigger', type: 'trigger' },
            { id: 'email', type: 'function_email' },
        ],
    }) as unknown as HogFlowMinimalApi

const schedule = (
    n: number,
    rrule: string,
    starts_at: string,
    status: HogFlowScheduleApi['status'] = 'active'
): HogFlowScheduleApi => ({
    id: `0199e0aa-0000-7000-8000-0000000002${String(n).padStart(2, '0')}`,
    rrule,
    starts_at,
    timezone: 'UTC',
    status,
    next_run_at: null,
    created_at: starts_at,
    updated_at: starts_at,
})

const job = (id: string, status: HogFlowBatchJobApi['status'], created_at: string): HogFlowBatchJobApi =>
    ({ id, status, created_at }) as HogFlowBatchJobApi

const FLOWS: HogFlowMinimalApi[] = [
    flow(1, 'October product update', 'broadcasts', 'batch', PRIYA),
    flow(2, 'Weekly digest', null, 'batch', SAM),
    flow(3, 'Webinar reminder', 'broadcasts', 'batch', PRIYA),
    flow(4, 'Product tips: dashboards', null, 'batch', SAM),
    flow(5, 'Partner newsletter', 'broadcasts', 'batch', PRIYA),
    flow(6, 'Customer survey', 'broadcasts', 'batch', PRIYA),
    flow(7, 'Win-back: 30 days inactive', null, 'batch', SAM),
    flow(8, 'Trial ending reminder', null, 'batch', SAM),
    flow(9, 'Monthly account summary', null, 'schedule', SAM),
]

const SCHEDULES: Record<string, HogFlowScheduleApi[]> = {
    [flowId(1)]: [schedule(1, 'FREQ=DAILY;COUNT=1', '2026-10-20T11:00:00Z')],
    [flowId(2)]: [schedule(2, 'FREQ=WEEKLY;BYDAY=TU', '2026-09-01T09:00:00Z')],
    [flowId(3)]: [schedule(3, 'FREQ=DAILY;COUNT=1', '2026-10-20T15:00:00Z')],
    [flowId(4)]: [schedule(4, 'FREQ=DAILY;COUNT=1', '2026-10-20T17:30:00Z')],
    [flowId(6)]: [schedule(6, 'FREQ=DAILY;COUNT=1', '2026-10-14T10:00:00Z', 'completed')],
    [flowId(7)]: [schedule(7, 'FREQ=WEEKLY;INTERVAL=2;BYDAY=TH', '2026-10-08T10:00:00Z')],
    [flowId(8)]: [schedule(8, 'FREQ=WEEKLY;BYDAY=FR', '2026-09-04T16:00:00Z', 'paused')],
    [flowId(9)]: [schedule(9, 'FREQ=MONTHLY;BYMONTHDAY=25', '2026-09-25T08:00:00Z')],
}

const BATCH_JOBS: Record<string, HogFlowBatchJobApi[]> = {
    [flowId(2)]: [
        job('digest-oct-13', 'completed', '2026-10-13T09:00:04Z'),
        job('digest-oct-6', 'completed', '2026-10-06T09:00:03Z'),
        job('digest-sep-29', 'completed', '2026-09-29T09:00:05Z'),
    ],
    [flowId(5)]: [job('partner-oct-16', 'active', '2026-10-16T09:00:02Z')],
    [flowId(6)]: [job('survey-oct-14', 'completed', '2026-10-14T10:00:04Z')],
    [flowId(7)]: [job('win-back-oct-8', 'failed', '2026-10-08T10:00:06Z')],
}

function useCalendarMocks(flows: HogFlowMinimalApi[]): void {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/hog_flows/': (info) => {
                const trigger = new URL(info.request.url).searchParams.get('trigger') ?? '{}'
                const type = (JSON.parse(trigger) as { type?: string }).type
                const results = flows.filter((item) => (item.trigger as { type: string }).type === type)
                return [200, { count: results.length, next: null, previous: null, results }]
            },
            '/api/projects/:team_id/hog_flows/:id/schedules/': (info) => [
                200,
                SCHEDULES[info.params.id as string] ?? [],
            ],
            '/api/projects/:team_id/hog_flows/:id/batch_jobs/': (info) => [
                200,
                BATCH_JOBS[info.params.id as string] ?? [],
            ],
        },
    })
}

function CalendarAt({ view, anchor }: { view: 'month' | 'week'; anchor: string }): JSX.Element {
    useMountedLogic(sendCalendarLogic)
    const { setView, setAnchor } = useActions(sendCalendarLogic)
    useEffect(() => {
        setView(view)
        setAnchor(anchor)
    }, [setView, setAnchor, view, anchor])
    return <SendCalendar />
}

export const MonthView: StoryFn = () => {
    useCalendarMocks(FLOWS)
    return <SendCalendar />
}

// The week with four sends on one day, which a month cell cuts to three.
export const BusyWeek: StoryFn = () => {
    useCalendarMocks(FLOWS)
    return <CalendarAt view="week" anchor="2026-10-20" />
}
BusyWeek.parameters = {
    testOptions: { waitForLoadersToDisappear: true, waitForSelector: '[data-attr=send-calendar-week]' },
}

// Below 40rem the grid changes to a list of the days that have sends.
export const NarrowWidth: StoryFn = () => {
    useCalendarMocks(FLOWS)
    return (
        <div className="w-[28rem]">
            <SendCalendar />
        </div>
    )
}
NarrowWidth.parameters = {
    testOptions: { waitForLoadersToDisappear: true, waitForSelector: '[data-attr=send-calendar-list]' },
}

export const NothingScheduled: StoryFn = () => {
    useCalendarMocks([])
    return <SendCalendar />
}
NothingScheduled.parameters = {
    testOptions: { waitForLoadersToDisappear: true, waitForSelector: '[data-attr=send-calendar]' },
}
