import { buildAppBreakdown, buildReleaseBreakdown, MAX_VISIBLE_BANDS, parseReleaseRows } from './releaseBreakdown'

const BUCKET_KEYS = ['2026-06-01 00:00:00', '2026-06-02 00:00:00', '2026-06-03 00:00:00']
const PALETTE = ['#1', '#2', '#3', '#4', '#5', '#6', '#7']

function releaseRow(version: string, series: [string, number][]): unknown[] {
    return ['web', version, '', series]
}

describe('releaseBreakdown', () => {
    describe('parseReleaseRows', () => {
        // groupArray does not promise an order, so the pairs arrive shuffled. Reading them positionally
        // would draw each release's volume against the wrong days.
        it('projects out-of-order bucket pairs onto the bucket key order', () => {
            const rows = parseReleaseRows(
                [
                    releaseRow('1.2.0', [
                        ['2026-06-03 00:00:00', 7],
                        ['2026-06-01 00:00:00', 3],
                    ]),
                ],
                BUCKET_KEYS
            )

            expect(rows[0]).toMatchObject({
                namespace: 'web',
                version: '1.2.0',
                build: null,
                counts: [3, 0, 7],
                total: 10,
            })
        })

        it('drops buckets outside the selected window so the table and the chart agree', () => {
            const rows = parseReleaseRows(
                [
                    releaseRow('1.2.0', [
                        ['2026-05-20 00:00:00', 99],
                        ['2026-06-02 00:00:00', 4],
                    ]),
                ],
                BUCKET_KEYS
            )

            expect(rows[0].counts).toEqual([0, 4, 0])
            expect(rows[0].total).toBe(4)
        })
    })

    describe('buildReleaseBreakdown', () => {
        it('folds everything past the visible cap into one band that cannot be filtered', () => {
            const rows = parseReleaseRows(
                Array.from({ length: MAX_VISIBLE_BANDS + 3 }, (_, index) =>
                    releaseRow(`1.0.${index}`, [['2026-06-01 00:00:00', 100 - index]])
                ),
                BUCKET_KEYS
            )

            const breakdown = buildReleaseBreakdown(rows, BUCKET_KEYS, PALETTE)

            expect(breakdown.bands).toHaveLength(MAX_VISIBLE_BANDS + 1)
            expect(breakdown.bands[MAX_VISIBLE_BANDS]).toMatchObject({
                label: '3 other releases',
                filters: null,
            })
            expect(breakdown.groupCount).toBe(MAX_VISIBLE_BANDS + 3)
        })

        // Exceptions with no $app_version are the reason someone opens this panel, so they get their
        // own band rather than being folded in with the named releases, and it stays filterable.
        it('separates exceptions that carry no release', () => {
            const rows = parseReleaseRows(
                [releaseRow('1.2.0', [['2026-06-01 00:00:00', 30]]), ['', '', '', [['2026-06-01 00:00:00', 10]]]],
                BUCKET_KEYS
            )

            const breakdown = buildReleaseBreakdown(rows, BUCKET_KEYS, PALETTE)

            expect(breakdown.bands[1]).toMatchObject({ label: 'No release data', total: 10, share: 25 })
            expect(breakdown.bands[1].filters).toEqual([
                { key: '$app_namespace', value: null },
                { key: '$app_version', value: null },
                { key: '$app_build', value: null },
            ])
            expect(breakdown.groupCount).toBe(1)
            expect(breakdown.total).toBe(40)
        })

        it('labels a release with its app when the period spans more than one', () => {
            const rows = parseReleaseRows(
                [
                    ['web', '1.2.0', '', [['2026-06-01 00:00:00', 30]]],
                    ['ios', '4.1', '881', [['2026-06-01 00:00:00', 10]]],
                ],
                BUCKET_KEYS
            )

            expect(buildReleaseBreakdown(rows, BUCKET_KEYS, PALETTE).bands.map((band) => band.label)).toEqual([
                'web · 1.2.0',
                'ios · 4.1 (881)',
            ])
        })
    })

    describe('buildAppBreakdown', () => {
        // The app query groups by namespace, but the fold still has to merge several rows per app:
        // the release-shaped rows below are the shape parseReleaseRows produces for either query.
        it('merges every release of an app into one band, filtering on the namespace alone', () => {
            const rows = parseReleaseRows(
                [
                    ['web', '1.2.0', '', [['2026-06-01 00:00:00', 30]]],
                    ['web', '1.3.0', '', [['2026-06-02 00:00:00', 12]]],
                    ['ios', '4.1', '881', [['2026-06-01 00:00:00', 10]]],
                ],
                BUCKET_KEYS
            )

            const breakdown = buildAppBreakdown(rows, BUCKET_KEYS, PALETTE)

            expect(breakdown.bands.map((band) => band.label)).toEqual(['web', 'ios'])
            expect(breakdown.bands[0]).toMatchObject({ total: 42, counts: [30, 12, 0] })
            expect(breakdown.bands[0].filters).toEqual([{ key: '$app_namespace', value: 'web' }])
            expect(breakdown.groupCount).toBe(2)
            expect(breakdown.total).toBe(52)
        })

        // A release with a version but no namespace is a named release, yet it has no app — the two
        // breakdowns have to split it differently.
        it('counts a release with no namespace as having no app', () => {
            const rows = parseReleaseRows(
                [
                    ['web', '1.2.0', '', [['2026-06-01 00:00:00', 30]]],
                    ['', '9.9', '', [['2026-06-01 00:00:00', 10]]],
                ],
                BUCKET_KEYS
            )

            const breakdown = buildAppBreakdown(rows, BUCKET_KEYS, PALETTE)

            expect(breakdown.bands.map((band) => band.label)).toEqual(['web', 'No app data'])
            expect(breakdown.bands[1].filters).toEqual([{ key: '$app_namespace', value: null }])
            expect(buildReleaseBreakdown(rows, BUCKET_KEYS, PALETTE).groupCount).toBe(2)
        })
    })
})
