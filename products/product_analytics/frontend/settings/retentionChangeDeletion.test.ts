import { RetentionPeriods, retentionChangeDeletion } from './retentionChangeDeletion'

const DOWNGRADED: RetentionPeriods = {
    retentionMonths: 36,
    defaultMonths: 12,
    monthlyDefaultMonths: 18,
    planMonths: 12,
    nextMonthlyCleanupOn: '2026-12-03',
    passSchedule: null,
}

const ON_PLAN_DEFAULT: RetentionPeriods = {
    retentionMonths: 36,
    defaultMonths: 24,
    monthlyDefaultMonths: null,
    planMonths: 84,
    nextMonthlyCleanupOn: '2026-12-03',
    passSchedule: { scheduled_pass_on: '2027-02-03', first_pass_on: '2027-02-03', default_period_deletes: true },
}

describe('retentionChangeDeletion', () => {
    it.each([
        ['a shorter organization period past the plan', DOWNGRADED, null, { monthly: true, deletesOn: '2026-12-03' }],
        ['a longer organization period past the plan', { ...DOWNGRADED, monthlyDefaultMonths: 40 }, null, null],
        [
            'a shorter default the cleanup does not enforce',
            {
                ...ON_PLAN_DEFAULT,
                passSchedule: { scheduled_pass_on: null, first_pass_on: '2027-02-03', default_period_deletes: false },
            },
            null,
            null,
        ],
        ['a shorter plan default', ON_PLAN_DEFAULT, null, { monthly: false, deletesOn: '2027-02-03' }],
        [
            'a shorter own period',
            { ...DOWNGRADED, retentionMonths: 24 },
            12,
            { monthly: true, deletesOn: '2026-12-03' },
        ],
        ['a longer own period', { ...DOWNGRADED, retentionMonths: 12 }, 24, null],
        [
            'any period while the plan default applies',
            { ...ON_PLAN_DEFAULT, retentionMonths: null },
            84,
            { monthly: true, deletesOn: '2026-12-03' },
        ],
    ])('%s', (_name, periods, months, expected) => {
        expect(retentionChangeDeletion(periods, months)).toEqual(expected)
    })
})
