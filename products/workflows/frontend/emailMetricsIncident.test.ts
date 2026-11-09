import { Dayjs, dayjs } from 'lib/dayjs'

import { overlapsEmailMetricsIncident } from './emailMetricsIncident'

// Asia/Kolkata is UTC+05:30, so the affected hourly buckets (10:00-12:00 UTC) are 15:30-17:30 local time.
const local = (time: string): Dayjs => dayjs.tz(time, 'Asia/Kolkata')

describe('overlapsEmailMetricsIncident', () => {
    it.each([
        ['ends before the first affected hour', '2026-11-03 10:00', '2026-11-03 15:29:59', false],
        ['ends as the first affected hour starts', '2026-11-03 10:00', '2026-11-03 15:30:00', true],
        ['starts in the last second of the last affected hour', '2026-11-03 17:29:59', '2026-11-04 00:00', true],
        ['starts as the last affected hour ends', '2026-11-03 17:30:00', '2026-11-04 00:00', false],
        ['starts after the affected hours', '2026-11-04 00:00', '2026-11-05 00:00', false],
        ['spans the affected hours', '2026-10-27 00:00', '2026-11-10 00:00', true],
    ])('%s', (_, dateFrom, dateTo, expected) => {
        expect(overlapsEmailMetricsIncident(local(dateFrom), local(dateTo))).toBe(expected)
    })
})
