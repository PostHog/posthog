import { formatWeeklyChange, formatWeeklyRate, weeklyPageLabel } from './weeklyReport'

describe('weeklyReport', () => {
    it.each([
        [null, 'no answers'],
        [0.5, '50%'],
        [1 / 6, '16.7%'],
    ])('formats the rate %s as %s', (rate, expected) => {
        expect(formatWeeklyRate(rate)).toEqual(expected)
    })

    it.each([
        [null, 'new this week'],
        [0, 'no change'],
        [0.0004, 'no change'],
        [0.01, '+1 pt'],
        [-0.667, '-66.7 pts'],
    ])('formats the change %s as %s', (change, expected) => {
        expect(formatWeeklyChange(change)).toEqual(expected)
    })

    it.each([
        ['https://example.com/replay/', 'example.com/replay'],
        ['https://example.com/pricing?ref=ai#plans', 'example.com/pricing'],
        ['https://example.com', 'example.com'],
    ])('labels %s as %s', (url, expected) => {
        expect(weeklyPageLabel(url)).toEqual(expected)
    })
})
