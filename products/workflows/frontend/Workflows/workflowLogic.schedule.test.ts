import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { DEFAULT_STATE, ONE_TIME_RRULE } from './hogflows/steps/components/rrule-helpers'
import { HogFlowSchedule } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

const WEEKLY_MONDAY_RRULE = 'FREQ=WEEKLY;INTERVAL=1;BYDAY=MO'
const STARTS_AT = '2026-04-10T09:00:00.000Z'

const makeSchedule = (overrides: Partial<HogFlowSchedule> = {}): HogFlowSchedule => ({
    id: 'schedule-1',
    rrule: WEEKLY_MONDAY_RRULE,
    starts_at: STARTS_AT,
    timezone: 'UTC',
    ...overrides,
})

describe('workflowLogic schedule reducers', () => {
    let logic: ReturnType<typeof workflowLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = workflowLogic({ id: 'new', tabId: 'default' })
        logic.mount()
    })

    describe('initial state', () => {
        it('has default schedule state', () => {
            expect(logic.values.scheduleState).toEqual(DEFAULT_STATE)
            expect(logic.values.scheduleStartsAt).toBeNull()
            expect(logic.values.isScheduleRepeating).toBe(false)
            expect(logic.values.pendingSchedule).toBe(false)
        })
    })

    describe('setSchedules', () => {
        it('initializes reducers from a repeating schedule', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSchedules([makeSchedule()])
            }).toMatchValues({
                scheduleStartsAt: STARTS_AT,
                scheduleTimezone: 'UTC',
                isScheduleRepeating: true,
            })

            expect(logic.values.scheduleState.frequency).toBe('weekly')
            expect(logic.values.scheduleState.weekdays).toContain(0) // Monday
        })

        it('initializes reducers from a one-time schedule', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSchedules([makeSchedule({ rrule: ONE_TIME_RRULE })])
            }).toMatchValues({
                scheduleStartsAt: STARTS_AT,
                isScheduleRepeating: false,
                scheduleState: DEFAULT_STATE,
            })
        })

        it('resets to defaults when schedules list is empty', async () => {
            logic.actions.setSchedules([makeSchedule()])

            await expectLogic(logic, () => {
                logic.actions.setSchedules([])
            }).toMatchValues({
                scheduleStartsAt: null,
                isScheduleRepeating: false,
                scheduleState: DEFAULT_STATE,
            })
        })
    })

    describe('pendingSchedule selector', () => {
        it('returns false when no changes have been made', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSchedules([makeSchedule()])
            }).toMatchValues({
                pendingSchedule: false,
            })
        })

        it('returns schedule config when starts_at changes', async () => {
            logic.actions.setSchedules([makeSchedule()])
            const newStartsAt = '2026-05-01T10:00:00.000Z'

            await expectLogic(logic, () => {
                logic.actions.setScheduleStartsAt(newStartsAt)
            }).toMatchValues({
                pendingSchedule: {
                    rrule: expect.any(String),
                    starts_at: newStartsAt,
                    timezone: 'UTC',
                },
            })
        })

        it('returns schedule config when timezone changes', async () => {
            logic.actions.setSchedules([makeSchedule()])

            await expectLogic(logic, () => {
                logic.actions.setScheduleTimezone('US/Eastern', 'UTC')
            }).toMatchValues({
                pendingSchedule: {
                    rrule: expect.any(String),
                    // Wall clock stays 9:00 AM, UTC shifts from 09:00 to 13:00 (9:00 AM EDT = UTC-4)
                    starts_at: '2026-04-10T13:00:00.000Z',
                    timezone: 'US/Eastern',
                },
            })
        })

        it('returns ONE_TIME_RRULE when repeating is toggled off', async () => {
            logic.actions.setSchedules([makeSchedule()])

            await expectLogic(logic, () => {
                logic.actions.setScheduleRepeating(false)
            }).toMatchValues({
                pendingSchedule: {
                    rrule: ONE_TIME_RRULE,
                    starts_at: STARTS_AT,
                    timezone: 'UTC',
                },
            })
        })

        it('returns null when starts_at is cleared on existing schedule', async () => {
            logic.actions.setSchedules([makeSchedule()])

            await expectLogic(logic, () => {
                logic.actions.setScheduleStartsAt(null)
            }).toMatchValues({
                pendingSchedule: null,
            })
        })

        it('returns false when starts_at is null and no saved schedule exists', () => {
            expect(logic.values.pendingSchedule).toBe(false)
        })

        it('returns new schedule for a new workflow with no saved schedule', async () => {
            await expectLogic(logic, () => {
                logic.actions.setScheduleStartsAt(STARTS_AT)
                logic.actions.setScheduleRepeating(true)
            }).toMatchValues({
                pendingSchedule: {
                    rrule: expect.any(String),
                    starts_at: STARTS_AT,
                    timezone: expect.any(String),
                },
            })
        })
    })

    describe('hasUnsavedChanges', () => {
        it('is false after loading a saved schedule', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSchedules([makeSchedule()])
            }).toMatchValues({
                hasUnsavedChanges: false,
            })
        })

        it.each([
            ['timezone changes', () => logic.actions.setScheduleTimezone('US/Eastern')],
            ['frequency changes', () => logic.actions.setScheduleState({ ...DEFAULT_STATE, frequency: 'daily' })],
            ['date changes', () => logic.actions.setScheduleStartsAt('2026-05-01T10:00:00.000Z')],
            ['repeat is toggled off', () => logic.actions.setScheduleRepeating(false)],
            ['date is cleared', () => logic.actions.setScheduleStartsAt(null)],
        ])('is true when %s', (_, applyChange) => {
            logic.actions.setSchedules([makeSchedule()])
            applyChange()
            expect(logic.values.hasUnsavedChanges).toBe(true)
        })

        it('is false after resetting changes', async () => {
            logic.actions.setSchedules([makeSchedule()])
            logic.actions.setScheduleTimezone('US/Eastern')
            expect(logic.values.hasUnsavedChanges).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.resetWorkflow(logic.values.workflow)
            }).toMatchValues({
                hasUnsavedChanges: false,
            })
        })
    })

    describe('end-to-end scenarios', () => {
        it('scenario 1: new workflow - create schedule from scratch', async () => {
            // Pick a date, toggle repeat on, select weekly on Monday
            logic.actions.setScheduleStartsAt(STARTS_AT)
            logic.actions.setScheduleRepeating(true)
            logic.actions.setScheduleState({
                ...DEFAULT_STATE,
                frequency: 'weekly',
                weekdays: [0], // Monday
            })

            const pending = logic.values.pendingSchedule
            expect(pending).not.toBe(false)
            expect(pending).not.toBeNull()
            expect((pending as any).rrule).toContain('FREQ=WEEKLY')
            expect((pending as any).rrule).toContain('BYDAY=MO')
            expect((pending as any).starts_at).toBe(STARTS_AT)
        })

        it('scenario 2: edit existing schedule produces updated pendingSchedule', async () => {
            logic.actions.setSchedules([makeSchedule()])

            // Change frequency to daily
            logic.actions.setScheduleState({ ...DEFAULT_STATE, frequency: 'daily', interval: 1 })
            // Change timezone - wall clock stays 9:00 AM, UTC shifts
            logic.actions.setScheduleTimezone('US/Eastern', 'UTC')

            const pending = logic.values.pendingSchedule
            expect(pending).not.toBe(false)
            expect((pending as any).rrule).toContain('FREQ=DAILY')
            expect((pending as any).rrule).not.toContain('BYDAY')
            expect((pending as any).timezone).toBe('US/Eastern')
            expect((pending as any).starts_at).toBe('2026-04-10T13:00:00.000Z')
        })

        it('scenario 3: clear changes reverts end type and count', async () => {
            logic.actions.setSchedules([makeSchedule()])

            // Change end type to after_count with count 5
            logic.actions.setScheduleState({
                ...logic.values.scheduleState,
                endType: 'after_count',
                endCount: 5,
            })
            expect(logic.values.hasUnsavedChanges).toBe(true)

            // Clear changes
            await expectLogic(logic, () => {
                logic.actions.resetWorkflow(logic.values.workflow)
            }).toMatchValues({
                hasUnsavedChanges: false,
                pendingSchedule: false,
            })
            expect(logic.values.scheduleState.endType).toBe('never')
        })

        it('scenario 4: toggle repeat off produces one-time rrule', async () => {
            logic.actions.setSchedules([makeSchedule()])
            logic.actions.setScheduleRepeating(false)

            const pending = logic.values.pendingSchedule
            expect(pending).not.toBe(false)
            expect((pending as any).rrule).toBe(ONE_TIME_RRULE)
            expect((pending as any).starts_at).toBe(STARTS_AT)
        })

        it('scenario 5: clearing date on existing schedule produces null (delete)', async () => {
            logic.actions.setSchedules([makeSchedule()])
            logic.actions.setScheduleStartsAt(null)

            expect(logic.values.pendingSchedule).toBeNull()
        })

        it('scenario 6: no false dirty state after loading schedule', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSchedules([makeSchedule()])
            }).toMatchValues({
                hasUnsavedChanges: false,
                pendingSchedule: false,
            })
        })
    })

    describe('timezone reinterpretation', () => {
        it.each([
            ['Europe/Helsinki', '2026-04-10T06:00:00.000Z'], // UTC+3
            ['US/Eastern', '2026-04-10T13:00:00.000Z'], // EDT UTC-4
            ['Asia/Kolkata', '2026-04-10T03:30:00.000Z'], // UTC+5:30
            ['Pacific/Auckland', '2026-04-09T21:00:00.000Z'], // NZST UTC+12
            ['UTC', '2026-04-10T09:00:00.000Z'], // No shift
        ])('setScheduleStartsAtFromPicker reinterprets 9:00 AM as %s', (timezone, expected) => {
            logic.actions.setScheduleTimezone(timezone)
            logic.actions.setScheduleStartsAtFromPicker('2026-04-10T09:00:00.000Z')
            expect(logic.values.scheduleStartsAt).toBe(expected)
        })

        it('setScheduleStartsAtFromPicker with null clears starts_at', () => {
            logic.actions.setScheduleStartsAt(STARTS_AT)
            logic.actions.setScheduleStartsAtFromPicker(null)
            expect(logic.values.scheduleStartsAt).toBeNull()
        })

        it.each([
            ['US/Eastern', '2026-04-10T13:00:00.000Z'], // EDT UTC-4
            ['Asia/Kolkata', '2026-04-10T03:30:00.000Z'], // UTC+5:30
            ['Pacific/Auckland', '2026-04-09T21:00:00.000Z'], // NZST UTC+12
        ])('changing timezone to %s preserves wall-clock time', (newTimezone, expected) => {
            logic.actions.setSchedules([makeSchedule()]) // 09:00 UTC
            logic.actions.setScheduleTimezone(newTimezone, 'UTC')
            expect(logic.values.scheduleStartsAt).toBe(expected)
        })
    })

    describe('resetWorkflow', () => {
        it('restores schedule state from saved repeating schedule', async () => {
            logic.actions.setSchedules([makeSchedule()])
            logic.actions.setScheduleTimezone('US/Eastern', 'UTC')
            logic.actions.setScheduleRepeating(false)

            await expectLogic(logic, () => {
                logic.actions.resetWorkflow(logic.values.workflow)
            }).toMatchValues({
                scheduleTimezone: 'UTC',
                isScheduleRepeating: true,
                pendingSchedule: false,
            })
        })

        it('restores schedule state from saved one-time schedule', async () => {
            logic.actions.setSchedules([makeSchedule({ rrule: ONE_TIME_RRULE })])
            logic.actions.setScheduleRepeating(true)

            await expectLogic(logic, () => {
                logic.actions.resetWorkflow(logic.values.workflow)
            }).toMatchValues({
                isScheduleRepeating: false,
                scheduleStartsAt: STARTS_AT,
                pendingSchedule: false,
            })
        })

        it('clears schedule state when no saved schedule', async () => {
            logic.actions.setScheduleStartsAt(STARTS_AT)
            logic.actions.setScheduleRepeating(true)

            await expectLogic(logic, () => {
                logic.actions.resetWorkflow(logic.values.workflow)
            }).toMatchValues({
                scheduleStartsAt: null,
                isScheduleRepeating: false,
                pendingSchedule: false,
            })
        })
    })
})
