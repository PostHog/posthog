import { isValidLogsRetentionDays, logsRetentionDaysLabel } from './logsRetentionPeriod'

describe('logsRetentionPeriod', () => {
    it.each([
        [14, false, true],
        [30, false, true],
        [90, false, false],
        [14, true, true],
        [90, true, true],
        [360, true, true],
        [2580, true, true],
        [45, true, false],
        [2610, true, false],
        [0, true, false],
        [-30, true, false],
        [30.5, true, false],
    ])('isValidLogsRetentionDays(%i, allowCustom=%s) is %s', (days, allowCustom, expected) => {
        expect(isValidLogsRetentionDays(days, allowCustom)).toBe(expected)
    })

    it.each([
        [14, '14 days'],
        [90, '90 days'],
        [360, '1 year (360 days)'],
        [390, '13 months (390 days)'],
    ])('labels %i days as %s', (days, label) => {
        expect(logsRetentionDaysLabel(days)).toBe(label)
    })
})
