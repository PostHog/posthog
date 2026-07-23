import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { scannerOverviewLogic } from './scannerOverviewLogic'

const STATS = {
    status_counts: { total: 0, succeeded: 0, failed: 0, ineligible: 0, in_flight: 0, success_rate: null },
    coverage: { recent_sessions: 0, total_sessions: 0, recent_days: 14 },
    available_tags: ['checkout', 'onboarding'],
    monitor: null,
    classifier: null,
    scorer: null,
}

describe('scannerOverviewLogic', () => {
    let logic: ReturnType<typeof scannerOverviewLogic.build>
    let statsRequests: string[]

    beforeEach(() => {
        statsRequests = []
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
                '/api/projects/:team/vision/scanners/:id/impact/': {},
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

        await expectLogic(logic, () => logic.actions.setOverviewStatusFilter(['failed'])).toFinishAllListeners()
        expect(logic.values.hasActiveOverviewFilters).toBe(true)

        await expectLogic(logic, () => {
            logic.actions.setOverviewStatusFilter([])
            logic.actions.setOverviewDateRange('-30d', null)
        }).toFinishAllListeners()
        expect(logic.values.hasActiveOverviewFilters).toBe(true)
    })

    it('reloads stats with the active filters as query params', async () => {
        await expectLogic(logic).toFinishAllListeners()
        statsRequests = []

        await expectLogic(logic, () => {
            logic.actions.setOverviewStatusFilter(['failed'])
            logic.actions.setOverviewVerdictFilter(['no'])
            logic.actions.setOverviewTagFilter(['checkout'])
        }).toFinishAllListeners()

        // Only the overview reloads on these actions, so the newest stats request is its own.
        const url = new URL(statsRequests[statsRequests.length - 1])
        expect(url.searchParams.get('status')).toBe('failed')
        expect(url.searchParams.get('verdict')).toBe('no')
        expect(url.searchParams.get('tags')).toBe('checkout')
    })

    it('clearOverviewFilters resets the date back to the default, not null', async () => {
        await expectLogic(logic, () => {
            logic.actions.setOverviewDateRange('-90d', null)
            logic.actions.setOverviewStatusFilter(['failed'])
        }).toFinishAllListeners()

        // A null date would break the recent_days derivation the stats loader depends on.
        await expectLogic(logic, () => logic.actions.clearOverviewFilters()).toFinishAllListeners()
        expect(logic.values.overviewDateFrom).toBe('-14d')
        expect(logic.values.overviewStatusFilter).toEqual([])
        expect(logic.values.hasActiveOverviewFilters).toBe(false)
    })
})
