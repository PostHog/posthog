import { dayjs } from 'lib/dayjs'

import type { ObservationVersionMarkerApi } from '../generated/api.schemas'
import { fillLabelDays, versionAccuracyStrip } from './labelStats'

describe('labelStats', () => {
    describe('fillLabelDays', () => {
        it('expands sparse day counts into a contiguous window with zero-filled gaps', () => {
            // Date-only string parses as local midnight, keeping day boundaries stable across timezones.
            const today = dayjs('2026-07-03')
            const result = fillLabelDays(
                [
                    { date: '2026-07-01', up: 2, down: 1 },
                    { date: '2026-07-03', up: 0, down: 3 },
                    { date: '2026-05-01', up: 9, down: 9 }, // outside the window, dropped
                ],
                5,
                today
            )

            expect(result.labels).toEqual(['Jun 29', 'Jun 30', 'Jul 1', 'Jul 2', 'Jul 3'])
            // Version markers match bars on these, so they must be full dates, not year-less labels.
            expect(result.dates).toEqual(['2026-06-29', '2026-06-30', '2026-07-01', '2026-07-02', '2026-07-03'])
            expect(result.up).toEqual([0, 0, 2, 0, 0])
            expect(result.down).toEqual([0, 0, 1, 0, 3])
        })
    })

    describe('versionAccuracyStrip', () => {
        const marker = (version: number, up: number, down: number, total: number): ObservationVersionMarkerApi => ({
            date: '2026-07-01',
            version,
            prompt: '',
            up,
            down,
            total,
        })

        it('computes thumbs-up share and delta per rated version, marking the active one current', () => {
            const strip = versionAccuracyStrip([marker(2, 2, 1, 10), marker(1, 1, 3, 8)], 2)
            expect(strip).toEqual([
                { version: 1, rated: 4, scanned: 8, pct: 25, delta: null, isCurrent: false },
                { version: 2, rated: 3, scanned: 10, pct: 67, delta: 42, isCurrent: true },
            ])
        })

        it('keeps the active version visible while scanned but unrated', () => {
            const strip = versionAccuracyStrip([marker(1, 1, 1, 4), marker(2, 3, 1, 6), marker(3, 0, 0, 5)], 3)
            expect(strip).toEqual([
                { version: 1, rated: 2, scanned: 4, pct: 50, delta: null, isCurrent: false },
                { version: 2, rated: 4, scanned: 6, pct: 75, delta: 25, isCurrent: false },
                { version: 3, rated: 0, scanned: 5, pct: null, delta: null, isCurrent: true },
            ])
        })

        it('appends a placeholder for an applied version that has no marker yet', () => {
            const strip = versionAccuracyStrip([marker(1, 2, 0, 3)], 2)
            expect(strip).toEqual([
                { version: 1, rated: 2, scanned: 3, pct: 100, delta: null, isCurrent: false },
                { version: 2, rated: 0, scanned: 0, pct: null, delta: null, isCurrent: true },
            ])
        })

        it.each([
            ['a single rated version compares nothing', [marker(1, 2, 1, 5)], 1],
            ['unrated non-active versions are dropped', [marker(1, 0, 0, 5), marker(2, 2, 1, 6)], 2],
        ])('returns no chips when %s', (_name, markers, activeVersion) => {
            expect(versionAccuracyStrip(markers, activeVersion)).toEqual([])
        })
    })
})
