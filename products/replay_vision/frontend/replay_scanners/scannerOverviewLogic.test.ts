import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { observationsDrilldownSearchParams, scannerOverviewLogic } from './scannerOverviewLogic'

const STATS = {
    status_counts: { total: 0, succeeded: 0, failed: 0, ineligible: 0, in_flight: 0, success_rate: null },
    coverage: { recent_sessions: 0, total_sessions: 0, recent_days: 14 },
    available_tags: ['checkout', 'onboarding'],
    monitor: null,
    classifier: null,
    scorer: null,
}

const IMPACT = { affected_sessions: 0, affected_users: 0, sessions_without_user: 0, window_days: 14 }

describe('scannerOverviewLogic', () => {
    let statsRequests: string[]
    let impactRequests: string[]

    beforeEach(() => {
        statsRequests = []
        impactRequests = []
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/:id/': {
                    id: 'sid',
                    name: 'm',
                    scanner_type: 'monitor',
                    scanner_config: { prompt: 'p' },
                    sampling_rate: 1,
                    enabled: true,
                },
                '/api/projects/:team/vision/scanners/:id/observations/': { results: [], count: 0 },
                '/api/projects/:team/vision/scanners/:id/impact/': ({ request }) => {
                    impactRequests.push(request.url)
                    return [200, IMPACT]
                },
                '/api/projects/:team/vision/scanners/:id/observations/stats/': ({ request }) => {
                    statsRequests.push(request.url)
                    return [200, STATS]
                },
            },
        })
        initKeaTests()
    })

    describe('with a mounted scanner', () => {
        let logic: ReturnType<typeof scannerOverviewLogic.build>

        beforeEach(() => {
            logic = scannerOverviewLogic({ scannerId: 'sid' })
            logic.mount()
        })

        afterEach(() => logic.unmount())

        it('treats the default date range as inactive but any pill or non-default date as active', async () => {
            await expectLogic(logic).toFinishAllListeners()
            // A spurious "active" here would surface a Clear button on an untouched Overview.
            expect(logic.values.hasActiveOverviewFilters).toBe(false)

            await expectLogic(logic, () => logic.actions.setOverviewVerdictFilter(['no'])).toFinishAllListeners()
            expect(logic.values.hasActiveOverviewFilters).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.setOverviewVerdictFilter([])
                logic.actions.setOverviewDateRange('-30d', null)
            }).toFinishAllListeners()
            expect(logic.values.hasActiveOverviewFilters).toBe(true)
        })

        it('reloads stats with the active filters as query params', async () => {
            await expectLogic(logic).toFinishAllListeners()
            statsRequests = []

            await expectLogic(logic, () => {
                logic.actions.setOverviewVerdictFilter(['no'])
                logic.actions.setOverviewTagFilter(['checkout'])
            }).toFinishAllListeners()

            // Only the overview reloads on these actions, so the newest stats request is its own.
            const url = new URL(statsRequests[statsRequests.length - 1])
            expect(url.searchParams.get('verdict')).toBe('no')
            expect(url.searchParams.get('tags')).toBe('checkout')
        })

        it('reloads impact with a window derived from the date range, clamped to the endpoint max', async () => {
            await expectLogic(logic).toFinishAllListeners()
            impactRequests = []

            await expectLogic(logic, () => logic.actions.setOverviewDateRange('-7d', null)).toFinishAllListeners()
            expect(new URL(impactRequests[impactRequests.length - 1]).searchParams.get('window_days')).toBe('7')

            // A range past the endpoint's 90-day cap must clamp, not send an out-of-range value the API rejects.
            await expectLogic(logic, () => logic.actions.setOverviewDateRange('-180d', null)).toFinishAllListeners()
            expect(new URL(impactRequests[impactRequests.length - 1]).searchParams.get('window_days')).toBe('90')
        })

        it('clearOverviewFilters resets the date back to the default, not null', async () => {
            await expectLogic(logic, () => {
                logic.actions.setOverviewDateRange('-90d', null)
                logic.actions.setOverviewVerdictFilter(['no'])
            }).toFinishAllListeners()

            // A null date would break the recent_days derivation the stats loader depends on.
            await expectLogic(logic, () => logic.actions.clearOverviewFilters()).toFinishAllListeners()
            expect(logic.values.overviewDateFrom).toBe('-14d')
            expect(logic.values.overviewVerdictFilter).toEqual([])
            expect(logic.values.hasActiveOverviewFilters).toBe(false)
        })

        describe('drillIntoObservations', () => {
            it('navigates to the observations tab filtered to the clicked day, with the monitor verdict', async () => {
                // The mocked scanner is a monitor, so the drill-down should carry verdict=yes.
                await expectLogic(logic, () => logic.actions.drillIntoObservations('2026-05-04')).toFinishAllListeners()
                expect(router.values.location.pathname).toContain(urls.replayVision('sid'))
                expect(router.values.searchParams).toMatchObject({
                    tab: 'observations',
                    date_from: '2026-05-04',
                    date_to: '2026-05-04',
                    verdict: 'yes',
                })
            })

            it('ignores clicks on buckets that cannot map to a day filter', async () => {
                const before = router.values.location.pathname
                await expectLogic(logic, () => logic.actions.drillIntoObservations(undefined)).toFinishAllListeners()
                expect(router.values.location.pathname).toBe(before)
            })
        })

        describe('creditLimitStats', () => {
            it('is null when the scanner has no limit, so callers render no panel instead of "0% of 0"', async () => {
                await expectLogic(logic).toFinishAllListeners()
                expect(logic.values.creditLimitStats).toBeNull()
            })

            it.each([
                { used: 200, limit: 1000, expectedPct: 20, expectedReached: false },
                { used: 1000, limit: 1000, expectedPct: 100, expectedReached: true },
                { used: 1200, limit: 1000, expectedPct: 100, expectedReached: true },
                // The server reports reached as soon as what's left can't cover one more scan, so this
                // must come from the API and not be re-derived from usedPct.
                { used: 990, limit: 1000, expectedPct: 99, expectedReached: true },
            ])(
                'derives usedPct $expectedPct and limitReached $expectedReached from used=$used, limit=$limit',
                async ({ used, limit, expectedPct, expectedReached }) => {
                    await expectLogic(logic, () =>
                        logic.actions.loadScannerSuccess({
                            ...logic.values.scanner,
                            credit_limit: limit,
                            credits_used_against_limit: used,
                            limit_reached: expectedReached,
                        })
                    ).toFinishAllListeners()
                    expect(logic.values.creditLimitStats).toEqual({
                        limit,
                        used,
                        usedPct: expectedPct,
                        limitReached: expectedReached,
                    })
                }
            )
        })
    })

    describe('observationsDrilldownSearchParams', () => {
        const day = (overrides: object = {}): Parameters<typeof observationsDrilldownSearchParams>[0] => ({
            day: '2026-05-04',
            interval: 'day',
            ...overrides,
        })

        it('maps a clicked day to an inclusive single-day observations filter', () => {
            expect(observationsDrilldownSearchParams(day())).toEqual({
                tab: 'observations',
                date_from: '2026-05-04',
                date_to: '2026-05-04',
            })
        })

        it('adds verdict=yes for monitor scanners, whose chart plots the yes rate', () => {
            expect(observationsDrilldownSearchParams(day({ scannerType: 'monitor' }))?.verdict).toBe('yes')
            expect(observationsDrilldownSearchParams(day({ scannerType: 'classifier' }))?.verdict).toBeUndefined()
        })

        const tagCases: [string, unknown, string | undefined][] = [
            ['plain tag', 'rageclick', 'rageclick'],
            ['single-value breakdown array', ['rageclick'], 'rageclick'],
            ['other bucket', '$$_posthog_breakdown_other_$$', undefined],
            ['null bucket', '$$_posthog_breakdown_null_$$', undefined],
            ['numeric breakdown', 42, undefined],
            ['empty string', '', undefined],
        ]

        it.each(tagCases)('breakdown handling: %s', (_label, breakdown, expected) => {
            expect(observationsDrilldownSearchParams(day({ breakdown }))?.tags).toEqual(expected)
        })

        it('slices datetime buckets to their date', () => {
            expect(observationsDrilldownSearchParams(day({ day: '2026-05-04 14:00:00' }))?.date_from).toBe('2026-05-04')
        })

        // Buckets without a single-day meaning have no Observations-tab equivalent, so the click is a no-op.
        const noOpCases: [string, object][] = [
            ['undefined day', { day: undefined }],
            ['numeric day', { day: 1753747200 }],
            ['non-date label', { day: 'previous' }],
            ['week interval', { interval: 'week' }],
        ]

        it.each(noOpCases)('returns null for %s', (_label, overrides) => {
            expect(observationsDrilldownSearchParams(day(overrides))).toBeNull()
        })
    })

    describe('firstScanPending', () => {
        let freshLogic: ReturnType<typeof scannerOverviewLogic.build>
        let scannerBody: Record<string, unknown>
        let statsBody: Record<string, unknown>
        let failRequests: boolean

        const SETTLED_STATS = {
            ...STATS,
            status_counts: { total: 3, succeeded: 3, failed: 0, ineligible: 0, in_flight: 0, success_rate: 1 },
        }

        beforeEach(() => {
            // A just-created scanner: watermark still at its seeded value 35 minutes before creation.
            scannerBody = {
                id: 'fresh',
                name: 'fresh',
                scanner_type: 'monitor',
                scanner_config: { prompt: 'p' },
                sampling_rate: 1,
                enabled: true,
                created_at: dayjs().subtract(2, 'minute').toISOString(),
                last_swept_at: dayjs().subtract(37, 'minute').toISOString(),
            }
            statsBody = STATS
            failRequests = false
            useMocks({
                get: {
                    '/api/projects/:team/vision/scanners/:id/': () => (failRequests ? [500, {}] : [200, scannerBody]),
                    '/api/projects/:team/vision/scanners/:id/observations/stats/': ({ request }) => {
                        statsRequests.push(request.url)
                        return failRequests ? [500, {}] : [200, statsBody]
                    },
                },
            })
            freshLogic = scannerOverviewLogic({ scannerId: 'fresh' })
        })

        afterEach(() => {
            freshLogic.unmount()
            jest.useRealTimers()
        })

        it('is true for a fresh scanner awaiting its first sweep, except while overview filters slice the data', async () => {
            freshLogic.mount()
            await expectLogic(freshLogic).toFinishAllListeners()
            expect(freshLogic.values.firstScanPending).toBe(true)

            // Filters mean the user is inspecting data, so the normal panels must render.
            await expectLogic(freshLogic, () =>
                freshLogic.actions.setOverviewVerdictFilter(['no'])
            ).toFinishAllListeners()
            expect(freshLogic.values.firstScanPending).toBe(false)

            // A filtered flip must not latch as settled: clearing the filter brings the panel back.
            await expectLogic(freshLogic, () => freshLogic.actions.clearOverviewFilters()).toFinishAllListeners()
            expect(freshLogic.values.firstScanPending).toBe(true)
        })

        it('polls stats in the background while pending and stops once observations settle', async () => {
            // toFinishAllListeners hangs under fake timers (msw resolves responses on the clock),
            // so the whole test advances fake time instead, which also flushes microtasks.
            jest.useFakeTimers()
            freshLogic.mount()
            await jest.advanceTimersByTimeAsync(1_000)
            expect(freshLogic.values.firstScanPending).toBe(true)

            // Pending arms a background reload on the calmer first-scan interval. Each tick refreshes
            // stats and the watermark only; reloading impact per tick would triple the request count.
            const before = statsRequests.length
            const impactBefore = impactRequests.length
            await jest.advanceTimersByTimeAsync(16_000)
            expect(statsRequests.length).toBe(before + 1)
            expect(impactRequests.length).toBe(impactBefore)

            // Once observations settle, the pending state dissolves and polling stops.
            statsBody = SETTLED_STATS
            await jest.advanceTimersByTimeAsync(16_000)
            expect(freshLogic.values.firstScanPending).toBe(false)

            const after = statsRequests.length
            await jest.advanceTimersByTimeAsync(60_000)
            expect(statsRequests.length).toBe(after)
        })

        it('dissolves once the first sweep completes even when it matched nothing', async () => {
            jest.useFakeTimers()
            freshLogic.mount()
            await jest.advanceTimersByTimeAsync(1_000)
            expect(freshLogic.values.firstScanPending).toBe(true)

            // Stats stay all-zero forever here, so only the poll refetching the scanner's advanced
            // sweep watermark can clear pending before the stuck-scan cap.
            scannerBody = { ...scannerBody, last_swept_at: dayjs().toISOString() }
            await jest.advanceTimersByTimeAsync(16_000)
            expect(freshLogic.values.firstScanPending).toBe(false)
        })

        it('stays dissolved once it settles, even if a later check reports new work in flight', async () => {
            jest.useFakeTimers()
            freshLogic.mount()
            await jest.advanceTimersByTimeAsync(1_000)
            expect(freshLogic.values.firstScanPending).toBe(true)

            scannerBody = { ...scannerBody, last_swept_at: dayjs().toISOString() }
            await jest.advanceTimersByTimeAsync(16_000)
            expect(freshLogic.values.firstScanPending).toBe(false)

            // A follow-up sweep queueing observations must not swap the charts back out for the spinner.
            statsBody = { ...STATS, status_counts: { ...STATS.status_counts, total: 2, in_flight: 2 } }
            freshLogic.actions.loadOverviewStats()
            await jest.advanceTimersByTimeAsync(1_000)
            expect(freshLogic.values.firstScanPending).toBe(false)
        })

        it('keeps polling through a transient outage while pending, without toasting each retry', async () => {
            jest.useFakeTimers()
            const toastSpy = jest.spyOn(lemonToast, 'error')
            freshLogic.mount()
            await jest.advanceTimersByTimeAsync(1_000)
            expect(freshLogic.values.firstScanPending).toBe(true)

            // A stopped poll would freeze the pending panel, which hides every in-page reload control.
            failRequests = true
            await jest.advanceTimersByTimeAsync(16_000)
            expect(freshLogic.values.firstScanPending).toBe(true)
            expect(toastSpy).not.toHaveBeenCalled()

            failRequests = false
            statsBody = SETTLED_STATS
            await jest.advanceTimersByTimeAsync(16_000)
            expect(freshLogic.values.firstScanPending).toBe(false)
        })

        it('surfaces repeated failed checks on the panel instead of spinning silently', async () => {
            jest.useFakeTimers()
            freshLogic.mount()
            await jest.advanceTimersByTimeAsync(1_000)
            expect(freshLogic.values.firstScanCheckFailing).toBe(false)

            failRequests = true
            await jest.advanceTimersByTimeAsync(48_000)
            expect(freshLogic.values.firstScanPending).toBe(true)
            expect(freshLogic.values.firstScanCheckFailing).toBe(true)

            // One good response clears the failure notice.
            failRequests = false
            await jest.advanceTimersByTimeAsync(16_000)
            expect(freshLogic.values.firstScanCheckFailing).toBe(false)
        })

        it('caps a stuck first scan at an hour even when every check fails, then stops polling', async () => {
            jest.useFakeTimers()
            freshLogic.mount()
            await jest.advanceTimersByTimeAsync(1_000)
            expect(freshLogic.values.firstScanPending).toBe(true)

            // A dead endpoint (say the scanner was deleted in another tab) must still hit the age cap:
            // failed checks advance the selector's clock input, so pending can't stick forever.
            failRequests = true
            await jest.advanceTimersByTimeAsync(61 * 60_000)
            expect(freshLogic.values.firstScanPending).toBe(false)

            const after = statsRequests.length
            await jest.advanceTimersByTimeAsync(60_000)
            expect(statsRequests.length).toBe(after)
        })
    })
})
