import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { recommendationsTabLogic } from '../recommendations/recommendationsTabLogic'
import type { ErrorTrackingRecommendation } from '../recommendations/types'
import { impactTabLogic } from './impactTabLogic'

const recommendation = (
    type: ErrorTrackingRecommendation['type'],
    meta: Record<string, unknown>
): ErrorTrackingRecommendation => ({
    id: `${type}-id`,
    type,
    meta,
    completed: false,
    status: 'ready',
    computed_at: '2026-10-14T10:00:00Z',
    dismissed_at: null,
    created_at: '2026-10-14T10:00:00Z',
    updated_at: '2026-10-14T10:00:00Z',
})

const issue = (id: string): Record<string, unknown> => ({ id, name: 'Error', description: null, status: 'active' })

describe('impactTabLogic', () => {
    let logic: ReturnType<typeof impactTabLogic.build>

    beforeEach(async () => {
        initKeaTests()
        // The API returns types in alphabetical order, not in the priority order of the lenses.
        jest.spyOn(api.errorTracking, 'listRecommendations').mockResolvedValue({
            results: [
                recommendation('alerts', { alerts: [] }),
                recommendation('audience_slices', { window_hours: 24, issues: [issue('shared'), issue('browser')] }),
                recommendation('fires_on_leave', { window_hours: 24, evaluable: true, issues: [issue('unload')] }),
                recommendation('inflated_counts', { window_hours: 24, issues: [issue('loop')] }),
                recommendation('quick_leave', {
                    days: ['2026-10-12T10:00:00Z', '2026-10-05T10:00:00Z'],
                    min_page_seconds: 3,
                    quick_leave_seconds: 10,
                    return_hours: 24,
                    evaluable: true,
                    issues: [issue('shared')],
                }),
            ],
        })
        logic = impactTabLogic()
        logic.mount()
        await expectLogic(recommendationsTabLogic).toDispatchActions(['setRecommendations'])
    })

    afterEach(() => {
        logic.unmount()
    })

    it('opens on every lens but the noise lenses in priority order and keeps lenses out of the recommendations tab', () => {
        expect(recommendationsTabLogic.values.visibleRecommendations.map((r) => r.type)).toEqual(['alerts'])
        expect(logic.values.activeView).toEqual('all')
        expect(logic.values.viewStatus).toEqual('ready')
        // Fires as people leave and Repeats in a loop explain noise, so All leaves their issues out.
        expect(logic.values.activeFindings.map((finding) => [finding.lens, finding.issue.id])).toEqual([
            ['quick_leave', 'shared'],
            ['audience_slices', 'shared'],
            ['audience_slices', 'browser'],
        ])
        expect(logic.values.totalCount).toEqual(3)
        expect(logic.values.lensCounts).toMatchObject({ fires_on_leave: 1, inflated_counts: 1 })
    })

    it('lists only the items of the lens someone picks', () => {
        logic.actions.selectView('audience_slices')

        expect(logic.values.activeFindings.map((finding) => [finding.lens, finding.issue.id])).toEqual([
            ['audience_slices', 'shared'],
            ['audience_slices', 'browser'],
        ])
    })

    it('follows the lens in the URL without counting it as a pick, and goes back to all when it leaves', () => {
        const capture = jest.spyOn(posthog, 'capture')

        router.actions.push(urls.errorTracking({ activeTab: 'impact', lens: 'inflated_counts' }))
        expect(logic.values.activeView).toEqual('inflated_counts')

        router.actions.push(urls.errorTracking({ activeTab: 'impact' }))
        expect(logic.values.activeView).toEqual('all')
        expect(capture).not.toHaveBeenCalledWith('error_tracking_impact_lens_selected', expect.anything())
    })
})
