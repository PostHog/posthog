import { Meta, StoryFn } from '@storybook/react'
import { BindLogic, useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { dayjs } from 'lib/dayjs'

import { useStorybookMocks } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import type { AnyPropertyFilter } from '~/types'

import type { MessageCategoryApi } from 'products/messaging/frontend/generated/api.schemas'
import type {
    HogFlowScheduleApi,
    SendCalendarBatchJobApi,
    SendCalendarFlowApi,
    UserBasicApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { broadcastWizardLogic } from '../Broadcasts/broadcastWizardLogic'
import { SendCalendar } from './SendCalendar'
import { sendCalendarLogic } from './sendCalendarLogic'
import { SendCalendarSendDetails } from './SendCalendarSendDetails'
import { CalendarSend, describeRepeat, scheduleSendTimes, sendAudience } from './sendCalendarUtils'
import { SendDayPicker } from './SendDayPicker'

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

const category = (n: number, name: string): MessageCategoryApi =>
    ({
        id: `0199e0aa-0000-7000-8000-0000000003${String(n).padStart(2, '0')}`,
        key: name.toLowerCase().replace(/\W+/g, '-'),
        name,
        category_type: 'marketing',
    }) as MessageCategoryApi

const PRODUCT_UPDATES = category(1, 'Product updates')
const NEWSLETTER = category(2, 'Newsletter')
const EVENT_REMINDERS = category(4, 'Event reminders')
const CATEGORIES = [PRODUCT_UPDATES, NEWSLETTER, EVENT_REMINDERS]

const cohort = (id: number, name: string, count: number, is_static = false): Record<string, unknown> => ({
    id,
    name,
    count,
    is_static,
    is_calculating: false,
    deleted: false,
    filters: { properties: { type: 'OR', values: [] } },
    groups: [],
})

const COHORTS = [
    cohort(21, 'Active trial users', 1204),
    cohort(22, 'Newsletter subscribers', 18450),
    cohort(23, 'Webinar sign-ups', 312, true),
    cohort(24, 'Partners', 86, true),
]

const inCohort = (id: number): Record<string, unknown> => ({ key: 'id', type: 'cohort', value: id })
const personProperty = (key: string, operator: string, value: unknown): Record<string, unknown> => ({
    key,
    type: 'person',
    operator,
    value,
})

interface FlowRecipients {
    audience?: Record<string, unknown>[]
    to?: string
    category?: MessageCategoryApi
}

const flow = (
    n: number,
    name: string,
    origin_product: 'broadcasts' | null,
    trigger: 'batch' | 'schedule',
    created_by: UserBasicApi,
    { audience = [], to = '{{ person.properties.email }}', category }: FlowRecipients = {}
): SendCalendarFlowApi =>
    ({
        id: flowId(n),
        name,
        origin_product,
        created_by,
        user_access_level: 'editor',
        trigger_type: trigger,
        audience_properties: trigger === 'batch' ? audience : [],
        audience_type: null,
        email_to: trigger === 'schedule' ? to : null,
        message_category_id: category?.id ?? null,
        schedules: SCHEDULES[flowId(n)] ?? [],
        batch_jobs: BATCH_JOBS[flowId(n)] ?? [],
    }) as SendCalendarFlowApi

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

const job = (id: string, status: SendCalendarBatchJobApi['status'], created_at: string): SendCalendarBatchJobApi => ({
    id,
    status,
    created_at,
})

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

const BATCH_JOBS: Record<string, SendCalendarBatchJobApi[]> = {
    [flowId(2)]: [
        job('digest-oct-13', 'completed', '2026-10-13T09:00:04Z'),
        job('digest-oct-6', 'completed', '2026-10-06T09:00:03Z'),
        job('digest-sep-29', 'completed', '2026-09-29T09:00:05Z'),
    ],
    [flowId(5)]: [job('partner-oct-16', 'active', '2026-10-16T09:00:02Z')],
    [flowId(6)]: [job('survey-oct-14', 'completed', '2026-10-14T10:00:04Z')],
    [flowId(7)]: [job('win-back-oct-8', 'failed', '2026-10-08T10:00:06Z')],
}

const FLOWS: SendCalendarFlowApi[] = [
    flow(1, 'October product update', 'broadcasts', 'batch', PRIYA, {
        audience: [inCohort(21), personProperty('email', 'is_set', 'is_set')],
        category: PRODUCT_UPDATES,
    }),
    flow(2, 'Weekly digest', null, 'batch', SAM, { audience: [inCohort(22)], category: NEWSLETTER }),
    flow(3, 'Webinar reminder', 'broadcasts', 'batch', PRIYA, { audience: [inCohort(23)], category: EVENT_REMINDERS }),
    flow(4, 'Product tips: dashboards', null, 'batch', SAM, {
        audience: [inCohort(21), personProperty('plan', 'exact', ['free'])],
        category: PRODUCT_UPDATES,
    }),
    flow(5, 'Partner newsletter', 'broadcasts', 'batch', PRIYA, { audience: [inCohort(24)], category: NEWSLETTER }),
    flow(6, 'Customer survey', 'broadcasts', 'batch', PRIYA),
    flow(7, 'Win-back: 30 days inactive', null, 'batch', SAM, {
        audience: [personProperty('days_since_last_seen', 'gt', 30)],
        category: PRODUCT_UPDATES,
    }),
    flow(8, 'Trial ending reminder', null, 'batch', SAM, { audience: [inCohort(21)], category: PRODUCT_UPDATES }),
    flow(9, 'Monthly metrics report', null, 'schedule', SAM, { to: 'finance@example.com' }),
]

function useCalendarMocks(flows: SendCalendarFlowApi[]): void {
    useStorybookMocks({
        get: {
            // The server returns only the runs inside the requested range.
            '/api/projects/:team_id/hog_flows/send_calendar/': (info) => {
                const params = new URL(info.request.url).searchParams
                const [start, end] = [dayjs(params.get('start')), dayjs(params.get('end'))]
                const inRange = (run: SendCalendarBatchJobApi): boolean =>
                    !dayjs(run.created_at).isBefore(start) && dayjs(run.created_at).isBefore(end)
                return [200, flows.map((item) => ({ ...item, batch_jobs: item.batch_jobs.filter(inRange) }))]
            },
            '/api/projects/:team_id/cohorts/': toPaginatedResponse(COHORTS),
            '/api/projects/:team_id/cohorts/:id/': (info) => {
                const match = COHORTS.find((item) => String(item.id) === info.params.id)
                return match ? [200, match] : [404, { detail: 'Not found.' }]
            },
            '/api/projects/:team_id/messaging_categories/': toPaginatedResponse(CATEGORIES),
        },
    })
}

// The test runner shrinks the story root to its content, and a container query root has no width of its own.
function FullWidthCalendar(): JSX.Element {
    return (
        <div className="w-[75rem]">
            <SendCalendar />
        </div>
    )
}

function CalendarAt({ view, anchor }: { view: 'month' | 'week'; anchor: string }): JSX.Element {
    useMountedLogic(sendCalendarLogic)
    const { setView, setAnchor } = useActions(sendCalendarLogic)
    useEffect(() => {
        setView(view)
        setAnchor(anchor)
    }, [setView, setAnchor, view, anchor])
    return <FullWidthCalendar />
}

export const MonthView: StoryFn = () => {
    useCalendarMocks(FLOWS)
    return <FullWidthCalendar />
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
    return <FullWidthCalendar />
}
NothingScheduled.parameters = {
    testOptions: { waitForLoadersToDisappear: true, waitForSelector: '[data-attr=send-calendar]' },
}

const detailsSend = (item: SendCalendarFlowApi): CalendarSend => {
    const itemSchedule = SCHEDULES[item.id][0]
    return {
        key: `details-${item.id}`,
        flowId: item.id,
        name: item.name ?? '',
        kind: item.origin_product === 'broadcasts' ? 'broadcast' : 'workflow',
        state: 'planned',
        // The calendar shows each send at its next occurrence, not at the schedule's first one.
        at:
            scheduleSendTimes(itemSchedule, { start: dayjs(), end: dayjs().add(1, 'year') })[0] ??
            dayjs(itemSchedule.starts_at),
        repeat: describeRepeat(itemSchedule),
        isRecurring: itemSchedule.rrule !== 'FREQ=DAILY;COUNT=1',
        createdBy: item.created_by,
        schedule: itemSchedule,
        userAccessLevel: item.user_access_level ?? null,
        audience: sendAudience(item),
        categoryId: item.message_category_id,
    }
}

// Who a send goes to: a broadcast with a cohort audience, and a scheduled workflow that sends to one address.
export const SendDetails: StoryFn = () => {
    useCalendarMocks(FLOWS)
    return (
        <div className="flex items-start gap-4">
            {[detailsSend(FLOWS[0]), detailsSend(FLOWS[8])].map((send) => (
                <div key={send.key} className="rounded border bg-surface-primary">
                    <SendCalendarSendDetails send={send} />
                </div>
            ))}
        </div>
    )
}
SendDetails.parameters = {
    testOptions: { waitForLoadersToDisappear: true, waitForSelector: '[data-attr=send-calendar-audience]' },
}

function SendDayPickerFor({ sendAt }: { sendAt: string }): JSX.Element {
    const props = { id: 'new' }
    const { prefillFromLink, setScheduleMode, setSendAt } = useActions(broadcastWizardLogic(props))
    useEffect(() => {
        // A link prefill sets the audience without the recipient count that the audience picker starts.
        prefillFromLink({ properties: [inCohort(21)] as unknown as AnyPropertyFilter[] })
        setScheduleMode('later')
        setSendAt(sendAt)
    }, [prefillFromLink, setScheduleMode, setSendAt, sendAt])
    return (
        <BindLogic logic={broadcastWizardLogic} props={props}>
            <div className="w-[60rem]">
                <SendDayPicker />
            </div>
        </BindLogic>
    )
}

// A broadcast to a cohort that two other sends on the same day also reach, so the picker suggests another day.
export const SendDayPickerCrowded: StoryFn = () => {
    useCalendarMocks(FLOWS)
    return <SendDayPickerFor sendAt="2026-10-20T10:00:00.000Z" />
}
SendDayPickerCrowded.parameters = {
    testOptions: {
        waitForLoadersToDisappear: true,
        waitForSelector: '[data-attr=send-day-picker-use-suggestion] >> visible=true',
    },
}
