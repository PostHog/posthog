import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import {
    hogFlowsSchedulesList,
    hogFlowsSchedulesPartialUpdate,
    hogFlowsSendCalendarRetrieve,
} from 'products/workflows/frontend/generated/api'
import type {
    HogFlowScheduleApi,
    SendCalendarBatchJobApi,
    SendCalendarFlowApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { sendCalendarLogic } from './sendCalendarLogic'

jest.mock('products/workflows/frontend/generated/api', () => ({
    hogFlowsSendCalendarRetrieve: jest.fn(),
    hogFlowsSchedulesList: jest.fn(),
    hogFlowsSchedulesPartialUpdate: jest.fn(),
}))
jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

// The send sits a few days from the real clock, so the move into the future holds on any day the test runs.
const SEND_AT = dayjs.utc().add(3, 'day').startOf('day').add(10, 'hour')
const MOVED_AT = SEND_AT.add(2, 'day')
// The test team's week starts on Sunday.
const WEEK_OF_SEND = SEND_AT.subtract(SEND_AT.day(), 'day').startOf('day')
const NEXT_WEEK = WEEK_OF_SEND.add(7, 'day')

const ONE_TIME_RRULE = 'FREQ=DAILY;COUNT=1'
const ONE_TIME_RRULE_ON_SEND_WEEKDAY = `FREQ=WEEKLY;BYDAY=${['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'][SEND_AT.day()]};COUNT=1`

const SCHEDULE: HogFlowScheduleApi = {
    id: 'schedule-1',
    rrule: ONE_TIME_RRULE_ON_SEND_WEEKDAY,
    starts_at: SEND_AT.toISOString(),
    timezone: 'UTC',
    status: 'active',
    next_run_at: SEND_AT.toISOString(),
    created_at: SEND_AT.toISOString(),
    updated_at: SEND_AT.toISOString(),
}

const FLOW = {
    id: 'flow-1',
    name: 'October product update',
    origin_product: 'broadcasts',
    trigger_type: 'batch',
    audience_properties: [],
    user_access_level: 'editor',
    schedules: [SCHEDULE],
    batch_jobs: [],
} as unknown as SendCalendarFlowApi

const run = (id: string, at: dayjs.Dayjs): SendCalendarBatchJobApi => ({
    id,
    status: 'completed',
    created_at: at.toISOString(),
})

describe('sendCalendarLogic', () => {
    let logic: ReturnType<typeof sendCalendarLogic.build>
    let server: { schedule: HogFlowScheduleApi; runs: SendCalendarBatchJobApi[] }

    // The server keeps what the last save wrote, so the check before a move or Undo sees the saved schedule.
    // Like the real endpoint, the calendar endpoint returns the flow's open schedules whatever the range, but only
    // the runs created in [start, end).
    const serveFromStore = (): void => {
        server = { schedule: SCHEDULE, runs: [] }
        jest.mocked(hogFlowsSendCalendarRetrieve).mockImplementation(async (_projectId, { start, end }) => [
            {
                ...FLOW,
                schedules: [server.schedule].filter((item) => item.status !== 'completed'),
                batch_jobs: server.runs.filter(
                    (item) => !dayjs(item.created_at).isBefore(start) && dayjs(item.created_at).isBefore(end)
                ),
            },
        ])
        jest.mocked(hogFlowsSchedulesList).mockImplementation(async () => [server.schedule])
        jest.mocked(hogFlowsSchedulesPartialUpdate).mockImplementation(async (_projectId, _id, _scheduleId, fields) => {
            server.schedule = { ...server.schedule, ...fields }
            return server.schedule
        })
    }

    const savedStart = (): string | undefined => logic.values.scheduledFlows?.[0].schedules[0].starts_at

    const dropOnMovedDay = async (): Promise<void> => {
        const send = logic.values.sends.find((item) => item.flowId === FLOW.id)
        await expectLogic(logic, () =>
            logic.actions.moveSend(send!, MOVED_AT.format('YYYY-MM-DD'))
        ).toFinishAllListeners()
    }

    beforeEach(async () => {
        jest.clearAllMocks()
        initKeaTests()
        serveFromStore()
        logic = sendCalendarLogic()
        logic.mount()
        logic.actions.setView('week')
        logic.actions.setAnchor(SEND_AT.format('YYYY-MM-DD'))
        await expectLogic(logic).toDispatchActions(['loadScheduledFlowsSuccess']).toFinishAllListeners()
    })

    afterEach(() => logic.unmount())

    const TEAMMATE_EDIT = { ...SCHEDULE, rrule: 'FREQ=WEEKLY;BYDAY=TU,TH' }

    const clickUndo = async (): Promise<void> => {
        const undo = jest.mocked(lemonToast.success).mock.calls[0][1]?.button?.action
        await expectLogic(logic, () => undo?.()).toFinishAllListeners()
    }

    it('moves a one-time send to the day it was dropped on, and Undo moves it back', async () => {
        await dropOnMovedDay()

        expect(server.schedule).toEqual({ ...SCHEDULE, starts_at: MOVED_AT.toISOString(), rrule: ONE_TIME_RRULE })
        expect(savedStart()).toEqual(MOVED_AT.toISOString())

        await clickUndo()

        expect(server.schedule).toEqual(SCHEDULE)
        expect(savedStart()).toEqual(SCHEDULE.starts_at)
    })

    it('refuses a move when a teammate changed the schedule after the calendar loaded, and reloads', async () => {
        server.schedule = TEAMMATE_EDIT

        await dropOnMovedDay()

        expect(server.schedule).toEqual(TEAMMATE_EDIT)
        expect(lemonToast.error).toHaveBeenCalledWith(
            "Couldn't move October product update. Its schedule changed after the calendar loaded. Check the reloaded calendar and try again."
        )
        expect(logic.values.scheduledFlows?.[0].schedules).toEqual([TEAMMATE_EDIT])
    })

    it('refuses Undo when a teammate changed the schedule after the move', async () => {
        await dropOnMovedDay()
        const teammateEditAfterMove = { ...server.schedule, rrule: TEAMMATE_EDIT.rrule }
        server.schedule = teammateEditAfterMove

        await clickUndo()

        expect(server.schedule).toEqual(teammateEditAfterMove)
        expect(lemonToast.error).toHaveBeenCalledWith(
            "Couldn't undo the move. Its schedule changed after the calendar loaded. Check the reloaded calendar and try again."
        )
        expect(logic.values.scheduledFlows?.[0].schedules).toEqual([teammateEditAfterMove])
    })

    it('refuses to move a send whose time passed while the calendar was open, and reloads', async () => {
        const sentSchedule = { ...SCHEDULE, status: 'completed' as const, next_run_at: null }
        server.schedule = sentSchedule
        server.runs = [run('run-sent', SEND_AT)]
        jest.useFakeTimers({ advanceTimers: true, now: SEND_AT.add(1, 'hour').toDate() })

        try {
            await dropOnMovedDay()
        } finally {
            jest.useRealTimers()
        }

        expect(server.schedule).toEqual(sentSchedule)
        expect(lemonToast.error).toHaveBeenCalledWith(
            "Couldn't move October product update. This send already went out."
        )
        expect(logic.values.sends.map((send) => [send.key, send.state])).toEqual([['run-sent', 'sent']])
    })

    it('loads the runs of the new range when the person moves to another week', async () => {
        server.runs = [
            run('run-week-of-send', WEEK_OF_SEND.add(1, 'hour')),
            run('run-next-week-first', NEXT_WEEK),
            run('run-next-week-last', NEXT_WEEK.add(7, 'day').subtract(1, 'hour')),
        ]
        // From the first day of the week, any shift shorter than a week stays inside the same week.
        logic.actions.setAnchor(WEEK_OF_SEND.format('YYYY-MM-DD'))

        await expectLogic(logic, () => logic.actions.goForward()).toFinishAllListeners()

        expect(logic.values.range.start.toISOString()).toEqual(NEXT_WEEK.toISOString())
        expect(logic.values.sends.map((send) => send.key)).toEqual(['run-next-week-first', 'run-next-week-last'])
    })

    it('ignores a failed request for a week the person already left', async () => {
        let rejectFirst: (error: Error) => void = () => {}
        jest.mocked(hogFlowsSendCalendarRetrieve)
            .mockImplementationOnce(() => new Promise((_resolve, reject) => (rejectFirst = reject)))
            .mockResolvedValueOnce([FLOW])

        logic.actions.goForward()
        await expectLogic(logic, () => logic.actions.goForward()).toDispatchActions(['loadScheduledFlowsSuccess'])
        rejectFirst(new Error('Network error'))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.loadFailed).toBe(false)
        expect(logic.values.scheduledFlows).toEqual([FLOW])
    })

    it('puts the send back when the server rejects the move', async () => {
        jest.mocked(hogFlowsSchedulesPartialUpdate).mockRejectedValue({
            detail: 'Schedule must have at least one future occurrence.',
        })

        await dropOnMovedDay()

        expect(savedStart()).toEqual(SCHEDULE.starts_at)
        expect(lemonToast.error).toHaveBeenCalledWith(
            "Couldn't move October product update. Schedule must have at least one future occurrence."
        )
    })
})
