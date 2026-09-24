import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    HeatmapAnalysisResultApi,
    HeatmapAnalysisVariantApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { historicalHeatmapLogic } from './historicalHeatmapLogic'

const result: HeatmapAnalysisResultApi = {
    analysis: {
        id: '01900000-0000-7000-8000-000000000001',
        heatmap_id: '01900000-0000-7000-8000-000000000002',
        url: 'https://example.com/offers',
        date_from: '2025-11-02T04:00:00Z',
        date_to: '2025-11-03T05:00:00Z',
        viewport_width: 1440,
        status: 'completed',
        sampled_recordings: 0,
        excluded_recordings: 0,
        error: '',
        created_at: '2025-11-04T00:00:00Z',
        filters: { cohort_ids: [12], events: [{ id: 'purchase' }], filter_test_accounts: true },
    },
    variants: [],
    analyzed_visits: 0,
    unavailable_recordings: 0,
    excluded_clicks: 0,
}

describe('historicalHeatmapLogic', () => {
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, timezone: 'America/New_York' })
    })

    it('includes the whole final day across DST and marks changed filters without mutating the saved result', async () => {
        let submitted: unknown
        useMocks({
            post: {
                '/api/projects/:team_id/heatmap_analyses/': async ({ request }) => {
                    submitted = await request.json()
                    return result.analysis
                },
            },
            get: { '/api/projects/:team_id/heatmap_analyses/:id/': result },
        })
        const logic = historicalHeatmapLogic({ heatmapId: result.analysis.heatmap_id })
        logic.mount()
        const filters = heatmapDataLogic({ context: 'in-app' })
        filters.actions.setCommonFilters({
            date_from: '2025-11-02',
            date_to: '2025-11-02',
            cohort_ids: [12],
            events: [{ id: 'purchase' }],
            filter_test_accounts: true,
        })
        filters.actions.setWindowWidthOverride(1440)
        await expectLogic(logic, () => logic.actions.startAnalysis())
            .toDispatchActions(['startAnalysisSuccess'])
            .toMatchValues({ result, filtersChanged: false })
        expect(submitted).toMatchObject({
            date_from: '2025-11-02T04:00:00.000Z',
            date_to: '2025-11-03T05:00:00.000Z',
            viewport_width: 1440,
            cohort_ids: '[12]',
            events: '[{"id":"purchase"}]',
            filter_test_accounts: true,
        })
        expect(router.values.searchParams.historical_analysis).toBe(result.analysis.id)
        filters.actions.setWindowWidthOverride(1024)
        expect(logic.values.filtersChanged).toBe(true)
        expect(logic.values.result).toEqual(result)
        filters.actions.setWindowWidthOverride(1440)
        expect(logic.values.filtersChanged).toBe(false)
        filters.actions.setCommonFilters({
            ...filters.values.commonFilters,
            events: [{ id: 'purchase' }, { id: null }],
        })
        expect(logic.values.filtersChanged).toBe(false)
        logic.unmount()
    })

    it.each([true, false])(
        'restores filters only for an analysis belonging to this heatmap: %s',
        async (matchingHeatmap) => {
            useMocks({ get: { '/api/projects/:team_id/heatmap_analyses/:id/': result } })
            const logic = historicalHeatmapLogic({
                heatmapId: matchingHeatmap ? result.analysis.heatmap_id : 'another-heatmap',
            })
            logic.mount()
            await expectLogic(logic, () => logic.actions.loadAnalysis(result.analysis.id)).toDispatchActions(
                matchingHeatmap ? ['loadAnalysisSuccess'] : ['loadAnalysisFailure']
            )
            expect(logic.values.result).toEqual(matchingHeatmap ? result : null)
            expect(logic.values.error).toEqual(matchingHeatmap ? null : 'This analysis belongs to another heatmap.')
            if (matchingHeatmap) {
                expect(logic.values.commonFilters).toMatchObject({
                    date_from: '2025-11-02',
                    date_to: '2025-11-02',
                    cohort_ids: [12],
                    filter_test_accounts: true,
                })
                expect(logic.values.widthOverride).toBe(1440)
                expect(logic.values.filtersChanged).toBe(false)
            }
            logic.unmount()
        }
    )

    it('keeps the selected variant when refreshed results change order and navigates by observed date', async () => {
        const variants: HeatmapAnalysisVariantApi[] = [2, 1, 3].map((day) => ({
            id: `variant-${day}`,
            session_id: `recording-${day}`,
            window_id: 1,
            timestamp: day * 1000,
            first_seen: day * 1000,
            last_seen: day * 1000,
            width: 1440,
            height: 1600,
            recordings: 2,
            visits: 2,
            representative_replaced: false,
            alternatives: [],
            clicks: [],
        }))
        let response = { ...result, variants }
        useMocks({ get: { '/api/projects/:team_id/heatmap_analyses/:id/': () => [200, response] } })
        const logic = historicalHeatmapLogic({ heatmapId: result.analysis.heatmap_id })
        logic.mount()
        await expectLogic(logic, () => logic.actions.loadAnalysis(result.analysis.id)).toDispatchActions([
            'loadAnalysisSuccess',
        ])
        logic.actions.selectVariant('variant-2')
        expect(logic.values.selectedVariantIndex).toBe(1)
        response = { ...response, variants: [...variants].reverse() }
        await expectLogic(logic, () => logic.actions.loadAnalysis(result.analysis.id)).toDispatchActions([
            'loadAnalysisSuccess',
        ])
        expect(logic.values.selectedVariant?.id).toBe('variant-2')
        await expectLogic(logic, () => logic.actions.navigateVariant(-1)).toFinishAllListeners()
        expect(logic.values.selectedVariant?.id).toBe('variant-1')
        await expectLogic(logic, () => logic.actions.navigateVariant(-1)).toFinishAllListeners()
        expect(logic.values.selectedVariant?.id).toBe('variant-1')
        response = { ...response, variants: variants.filter((variant) => variant.id !== 'variant-1') }
        await expectLogic(logic, () => logic.actions.loadAnalysis(result.analysis.id)).toDispatchActions([
            'loadAnalysisSuccess',
        ])
        expect(logic.values.selectedVariant).toBeNull()
        logic.unmount()
    })

    it('loads the analysis named in the URL when the link changes while mounted', async () => {
        const other = { ...result, analysis: { ...result.analysis, id: 'other-analysis', viewport_width: 1024 } }
        useMocks({
            get: {
                '/api/projects/:team_id/heatmap_analyses/:id/': ({ params }) => [
                    200,
                    params.id === other.analysis.id ? other : result,
                ],
            },
        })
        router.actions.push('/heatmaps/example', { historical_analysis: result.analysis.id })
        const logic = historicalHeatmapLogic({ heatmapId: result.analysis.heatmap_id })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadAnalysisSuccess'])
        await expectLogic(logic, () =>
            router.actions.push('/heatmaps/example', { historical_analysis: other.analysis.id })
        ).toDispatchActions(['loadAnalysisSuccess'])
        expect(logic.values.result?.analysis.id).toBe(other.analysis.id)
        expect(logic.values.widthOverride).toBe(1024)
        logic.unmount()
    })
})
