import { router } from 'kea-router'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { TRACING_SCENE_VIEWER_ID, tracingFiltersLogic } from './tracingFiltersLogic'
import { tracingSceneLogic } from './tracingSceneLogic'

describe('tracingSceneLogic', () => {
    let logic: ReturnType<typeof tracingSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        // The featureFlags reducer persists to localStorage — reset so flags can't leak across tests.
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {})
        jest.spyOn(api.tracing, 'listSpans').mockResolvedValue({ results: [], hasMore: false })
        jest.spyOn(api.tracing, 'sparkline').mockResolvedValue({ results: [] })
        jest.spyOn(api.tracing, 'count').mockResolvedValue({ count: 0, traceCount: 0 })
        jest.spyOn(api.tracing, 'aggregate').mockResolvedValue({ results: [], compare: null })
        jest.spyOn(api.tracing, 'durationHistogram').mockResolvedValue({ results: [] })
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    const mountAt = (searchParams: Record<string, string>): ReturnType<typeof tracingFiltersLogic.build> => {
        router.actions.push('/tracing', searchParams)
        logic = tracingSceneLogic()
        logic.mount()
        return tracingFiltersLogic({ id: TRACING_SCENE_VIEWER_ID })
    }

    const enableOperationsView = (): void => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_OPERATIONS_VIEW]: true })
    }

    it('migrates legacy compare=true links to the custom time comparison', () => {
        const filtersLogic = mountAt({ compare: 'true' })
        expect(filtersLogic.values.comparison).toEqual({
            mode: 'time',
            preset: 'custom',
            currentWindowOverride: null,
            previousWindowOverride: null,
        })
    })

    it('reads the comparison URL param and writes it back without the legacy param', () => {
        const filtersLogic = mountAt({ comparison: JSON.stringify({ mode: 'time', preset: 'yesterday' }) })
        expect(filtersLogic.values.comparison).toMatchObject({ mode: 'time', preset: 'yesterday' })

        filtersLogic.actions.setComparison({
            mode: 'time',
            preset: 'last_week',
            currentWindowOverride: null,
            previousWindowOverride: null,
        })
        expect(JSON.parse(router.values.searchParams.comparison)).toEqual({ mode: 'time', preset: 'last_week' })
        expect(router.values.searchParams).not.toHaveProperty('compare')
    })

    it('ignores a malformed comparison param', () => {
        const filtersLogic = mountAt({ comparison: 'not-json' })
        expect(filtersLogic.values.comparison).toBeNull()
    })

    it('falls back to the legacy compare param when the comparison param is malformed', () => {
        const filtersLogic = mountAt({ comparison: '{"mode":"segment"}', compare: 'true' })
        expect(filtersLogic.values.comparison).toMatchObject({ mode: 'time', preset: 'custom' })
    })

    it('keeps the active comparison when navigating to a URL with a malformed comparison param', () => {
        const filtersLogic = mountAt({ comparison: JSON.stringify({ mode: 'time', preset: 'yesterday' }) })
        expect(filtersLogic.values.comparison).toMatchObject({ preset: 'yesterday' })

        router.actions.push('/tracing', { comparison: 'not-json' })
        expect(filtersLogic.values.comparison).toMatchObject({ preset: 'yesterday' })
    })

    it('opens the operations view from a ?view=operations deep link', () => {
        enableOperationsView()
        mountAt({ view: 'operations' })
        expect(logic.values.activeTracingTab).toBe('operations')
    })

    it('ignores ?view=operations when the operations view flag is off', () => {
        const filtersLogic = mountAt({ view: 'operations' })
        expect(logic.values.activeTracingTab).toBe('traces')
        expect(filtersLogic.values.viewMode).toBe('traces')
    })

    it('reconciles the operations tab when the flag resolves after a ?view=operations deep link', () => {
        // Flag not yet loaded: the deep link reads as the default traces view.
        mountAt({ view: 'operations' })
        expect(logic.values.activeTracingTab).toBe('traces')

        // Flag resolves late — the tab and URL reconcile without a navigation.
        enableOperationsView()
        expect(logic.values.activeTracingTab).toBe('operations')
        expect(logic.values.displayMode).toBe('operations')
        expect(router.values.searchParams.view).toBe('operations')
    })

    it('resets the operations tab to traces when the flag is disabled mid-session', () => {
        enableOperationsView()
        mountAt({ view: 'operations' })
        expect(logic.values.activeTracingTab).toBe('operations')

        featureFlagLogic.actions.setFeatureFlags([], {})
        expect(logic.values.activeTracingTab).toBe('traces')
        expect(logic.values.displayMode).toBe('traces')
        expect(router.values.searchParams).not.toHaveProperty('view')
    })

    it('writes the operations mode to the URL without clobbering the spans granularity', () => {
        enableOperationsView()
        const filtersLogic = mountAt({ view: 'spans' })
        expect(logic.values.displayMode).toBe('spans')

        logic.actions.setDisplayMode('operations')
        expect(logic.values.activeTracingTab).toBe('operations')
        expect(router.values.searchParams.view).toBe('operations')
        // The spans granularity only applies to the list view — it must survive underneath.
        expect(filtersLogic.values.viewMode).toBe('spans')

        logic.actions.setDisplayMode('spans')
        expect(logic.values.activeTracingTab).toBe('traces')
        expect(router.values.searchParams.view).toBe('spans')

        // Back/forward to a non-operations URL while on the operations tab resets the tab.
        logic.actions.setDisplayMode('operations')
        router.actions.push('/tracing', { view: 'spans' })
        expect(logic.values.activeTracingTab).toBe('traces')
        expect(logic.values.displayMode).toBe('spans')
    })

    // Guards the operations-tab rate denominator: on the operations tab the aggregate must always
    // cover the whole selected range (compare: false), even with a comparison active. A filter
    // change fires both the windowed aggregate (via runQuery) and the explicit full-range one, and
    // the full-range fetch must be the last one dispatched so it wins the abort race. Reorder those
    // two dispatches and the operations table would silently divide by the narrow compare sub-window.
    it('keeps the operations aggregate on the full range when a filter changes while comparing', async () => {
        silenceKeaLoadersErrors()
        enableOperationsView()
        const filtersLogic = mountAt({ comparison: JSON.stringify({ mode: 'time', preset: 'custom' }) })
        expect(filtersLogic.values.compareActive).toBe(true)

        const aggregateSpy = jest.spyOn(api.tracing, 'aggregate')
        logic.actions.setActiveTracingTab('operations')
        await new Promise((resolve) => setTimeout(resolve, 0))
        aggregateSpy.mockClear()

        filtersLogic.actions.setServiceNames(['svc-a'])
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(aggregateSpy).toHaveBeenLastCalledWith(
            expect.objectContaining({ compareFilter: expect.objectContaining({ compare: false }) }),
            expect.anything()
        )
        resumeKeaLoadersErrors()
    })

    // Same denominator guard for the bulk-restore path (back/forward, saved views): setFilters routes
    // through the data logic's runQuery, which fires a windowed aggregate while comparing. Without the
    // scene's full-range refetch the operations table would divide by the narrow compare sub-window.
    it('keeps the operations aggregate on the full range when filters are restored while comparing', async () => {
        silenceKeaLoadersErrors()
        enableOperationsView()
        const filtersLogic = mountAt({ comparison: JSON.stringify({ mode: 'time', preset: 'custom' }) })
        expect(filtersLogic.values.compareActive).toBe(true)

        const aggregateSpy = jest.spyOn(api.tracing, 'aggregate')
        logic.actions.setActiveTracingTab('operations')
        await new Promise((resolve) => setTimeout(resolve, 0))
        aggregateSpy.mockClear()

        // Restore a different filter set the way back/forward navigation does. The URL keeps
        // view=operations — a restored URL without it would (correctly) leave the operations tab.
        router.actions.push('/tracing', {
            comparison: JSON.stringify({ mode: 'time', preset: 'custom' }),
            serviceNames: 'svc-a',
            view: 'operations',
        })
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(aggregateSpy).toHaveBeenLastCalledWith(
            expect.objectContaining({ compareFilter: expect.objectContaining({ compare: false }) }),
            expect.anything()
        )
        resumeKeaLoadersErrors()
    })
})
