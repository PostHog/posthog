import { dayjs } from 'lib/dayjs'

import type { HogFlowApi, HogFlowBatchJobApi } from 'products/workflows/frontend/generated/api.schemas'

import { ONE_TIME_RRULE } from '../Workflows/hogflows/steps/components/rrule-helpers'
import { isBroadcastReadOnly } from './broadcastWizardLogic'

const RECURRING_RRULE = 'FREQ=WEEKLY;BYDAY=MO'

const broadcast = (status: string, schedules: { rrule: string; starts_at: string }[] = []): HogFlowApi =>
    ({ status, schedules }) as unknown as HogFlowApi

const future = (): string => dayjs().add(3, 'day').toISOString()
const past = (): string => dayjs().subtract(3, 'day').toISOString()
const job = (): HogFlowBatchJobApi => ({}) as HogFlowBatchJobApi

describe('isBroadcastReadOnly', () => {
    it.each([
        ['a draft', broadcast('draft'), [], false],
        [
            'a one-time send still in the future',
            broadcast('active', [{ rrule: ONE_TIME_RRULE, starts_at: future() }]),
            [],
            false,
        ],
        [
            'a one-time send whose time has passed',
            broadcast('active', [{ rrule: ONE_TIME_RRULE, starts_at: past() }]),
            [],
            true,
        ],
        [
            'a recurring send that has not fired',
            broadcast('active', [{ rrule: RECURRING_RRULE, starts_at: future() }]),
            [],
            true,
        ],
        ['an active broadcast with no schedule', broadcast('active'), [], true],
        ['an archived broadcast', broadcast('archived'), [], true],
    ])('returns %s -> %s', (_name, flow, jobs, expected) => {
        expect(isBroadcastReadOnly(flow, jobs as HogFlowBatchJobApi[])).toBe(expected)
    })

    it('locks a scheduled broadcast once it has actually sent', () => {
        // The window to edit closes at the first send, not at the scheduled time: a recurring send
        // still has a future occurrence, and editing it would not match what recipients already got.
        const scheduled = broadcast('active', [{ rrule: ONE_TIME_RRULE, starts_at: future() }])
        expect(isBroadcastReadOnly(scheduled, [])).toBe(false)
        expect(isBroadcastReadOnly(scheduled, [job()])).toBe(true)
    })
})
