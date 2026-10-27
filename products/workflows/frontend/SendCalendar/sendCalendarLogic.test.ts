import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import {
    hogFlowsSchedulesList,
    hogFlowsSchedulesPartialUpdate,
    hogFlowsSendCalendarRetrieve,
} from 'products/workflows/frontend/generated/api'
import type { HogFlowScheduleApi, SendCalendarFlowApi } from 'products/workflows/frontend/generated/api.schemas'

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

const SCHEDULE: HogFlowScheduleApi = {
    id: 'schedule-1',
    rrule: 'FREQ=DAILY;COUNT=1',
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

describe('sendCalendarLogic', () => {
    let logic: ReturnType<typeof sendCalendarLogic.build>

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
        jest.mocked(hogFlowsSendCalendarRetrieve).mockResolvedValue([FLOW])
        jest.mocked(hogFlowsSchedulesList).mockResolvedValue([SCHEDULE])
        logic = sendCalendarLogic()
        logic.mount()
        logic.actions.setView('week')
        logic.actions.setAnchor(SEND_AT.format('YYYY-MM-DD'))
        await expectLogic(logic).toDispatchActions(['loadScheduledFlowsSuccess']).toFinishAllListeners()
    })

    afterEach(() => logic.unmount())

    // The server keeps what the last save wrote, so the check before Undo sees the moved schedule.
    const saveOnServer = (): void => {
        jest.mocked(hogFlowsSchedulesPartialUpdate).mockImplementation(async (_projectId, _id, _scheduleId, fields) => {
            const saved = { ...SCHEDULE, ...fields }
            jest.mocked(hogFlowsSchedulesList).mockResolvedValue([saved])
            return saved
        })
    }
    const TEAMMATE_EDIT = { ...SCHEDULE, rrule: 'FREQ=WEEKLY;BYDAY=TU,TH' }

    it('moves a one-time send to the day it was dropped on, and Undo moves it back', async () => {
        saveOnServer()

        await dropOnMovedDay()

        expect(hogFlowsSchedulesPartialUpdate).toHaveBeenLastCalledWith(expect.any(String), FLOW.id, SCHEDULE.id, {
            starts_at: MOVED_AT.toISOString(),
            rrule: SCHEDULE.rrule,
        })
        expect(savedStart()).toEqual(MOVED_AT.toISOString())

        const undo = jest.mocked(lemonToast.success).mock.calls[0][1]?.button?.action
        await expectLogic(logic, () => undo?.()).toFinishAllListeners()

        expect(hogFlowsSchedulesPartialUpdate).toHaveBeenLastCalledWith(expect.any(String), FLOW.id, SCHEDULE.id, {
            starts_at: SCHEDULE.starts_at,
            rrule: SCHEDULE.rrule,
        })
        expect(savedStart()).toEqual(SCHEDULE.starts_at)
    })

    it('refuses a move when a teammate changed the schedule after the calendar loaded, and reloads', async () => {
        jest.mocked(hogFlowsSchedulesList).mockResolvedValue([TEAMMATE_EDIT])

        await dropOnMovedDay()

        expect(hogFlowsSchedulesPartialUpdate).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalledWith(
            "Couldn't move October product update. Its schedule changed after the calendar loaded. Check the reloaded calendar and try again."
        )
        expect(savedStart()).toEqual(SCHEDULE.starts_at)
    })

    it('refuses Undo when a teammate changed the schedule after the move', async () => {
        saveOnServer()
        await dropOnMovedDay()
        jest.mocked(hogFlowsSchedulesList).mockResolvedValue([TEAMMATE_EDIT])

        const undo = jest.mocked(lemonToast.success).mock.calls[0][1]?.button?.action
        await expectLogic(logic, () => undo?.()).toFinishAllListeners()

        expect(hogFlowsSchedulesPartialUpdate).toHaveBeenCalledTimes(1)
        expect(lemonToast.error).toHaveBeenCalledWith(
            "Couldn't undo the move. Its schedule changed after the calendar loaded. Check the reloaded calendar and try again."
        )
    })

    it('refuses to move a send whose time passed while the calendar was open, and reloads', async () => {
        const send = logic.values.sends.find((item) => item.flowId === FLOW.id)!
        const elapsed = { ...send, at: dayjs.utc().subtract(1, 'hour') }

        await expectLogic(logic, () => logic.actions.applyMove(elapsed, 2, MOVED_AT.toISOString())).toDispatchActions([
            'loadScheduledFlows',
        ])

        expect(hogFlowsSchedulesPartialUpdate).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalledWith(
            "Couldn't move October product update. This send already went out."
        )
    })

    it('loads the runs of the new range when the person moves to another week', async () => {
        await expectLogic(logic, () => logic.actions.goForward()).toDispatchActions(['loadScheduledFlowsSuccess'])

        expect(hogFlowsSendCalendarRetrieve).toHaveBeenLastCalledWith(expect.any(String), {
            start: logic.values.range.start.toISOString(),
            end: logic.values.range.end.toISOString(),
        })
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
