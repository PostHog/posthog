import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

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
    let logic: ReturnType<typeof scannerOverviewLogic.build>
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
})
