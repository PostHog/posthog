import type { RangeValues } from '../rangePresets'
import { webAnalyticsInterval } from './interval'

const NOW = new Date(2026, 9, 14, 12).getTime()

describe('webAnalyticsInterval', () => {
    test.each<[string, RangeValues, string]>([
        ['today', { date_from: 'dStart', date_to: null }, 'hour'],
        ['the last 24 hours', { date_from: '-24h', date_to: null }, 'hour'],
        ['the last 7 days', { date_from: '-7d', date_to: null }, 'day'],
        ['the last 90 days', { date_from: '-90d', date_to: null }, 'day'],
        ['the last 180 days', { date_from: '-180d', date_to: null }, 'month'],
        ['all time', { date_from: 'all', date_to: null }, 'month'],
        ['one custom day', { date_from: '2026-10-01', date_to: '2026-10-01', explicitDate: false }, 'hour'],
        ['a custom week', { date_from: '2026-10-01', date_to: '2026-10-07', explicitDate: false }, 'day'],
        ['two custom weeks', { date_from: '2026-10-01', date_to: '2026-10-15', explicitDate: false }, 'week'],
        ['three custom months', { date_from: '2026-07-01', date_to: '2026-09-30', explicitDate: false }, 'month'],
    ])('charts %s like the web', (_name, values, interval) => {
        expect(webAnalyticsInterval(values, NOW)).toBe(interval)
    })
})
