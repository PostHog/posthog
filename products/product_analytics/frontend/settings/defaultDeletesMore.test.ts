import { DefaultDeletionInput, defaultDeletesMore } from './defaultDeletesMore'

const DOWNGRADED: DefaultDeletionInput = {
    retentionMonths: 36,
    defaultMonths: 12,
    monthlyDefaultMonths: 18,
    planMonths: 12,
    passSchedule: null,
}

describe('defaultDeletesMore', () => {
    it.each([
        ['a shorter organization period past the plan', DOWNGRADED, true],
        ['a longer organization period past the plan', { ...DOWNGRADED, monthlyDefaultMonths: 40 }, false],
        [
            'a shorter default the cleanup does not enforce',
            {
                retentionMonths: 36,
                defaultMonths: 24,
                monthlyDefaultMonths: null,
                planMonths: 84,
                passSchedule: { scheduled_pass_on: null, first_pass_on: '2027-02-03', default_period_deletes: false },
            },
            false,
        ],
    ])('%s', (_name, input, expected) => {
        expect(defaultDeletesMore(input)).toBe(expected)
    })
})
