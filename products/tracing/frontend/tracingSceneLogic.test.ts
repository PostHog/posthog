import { router } from 'kea-router'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { tracingDataLogic } from './tracingDataLogic'
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

    it.each([
        ['an uppercase hex trace id', '4BF92F3577B34DA6A3CE929D0E0E4736', '4BF92F3577B34DA6A3CE929D0E0E4736'],
        ['a lowercase hex trace id', '4bf92f3577b34da6a3ce929d0e0e4736', '4BF92F3577B34DA6A3CE929D0E0E4736'],
        ['a trace id with path characters', 'a/b', null],
    ])('opens the trace drawer from the URL only for %s', (_name, traceId, expected) => {
        jest.spyOn(api.tracing, 'getTrace').mockResolvedValue({ results: [], hasMore: false })
        mountAt({ trace: traceId })
        expect(logic.values.selectedTraceId).toBe(expected)
    })

    const LOWER_TRACE_ID = '4bf92f3577b34da6a3ce929d0e0e4736'
    const UPPER_TRACE_ID = '4BF92F3577B34DA6A3CE929D0E0E4736'

    it.each([
        ['a lowercase trace id', null, { trace: LOWER_TRACE_ID }, UPPER_TRACE_ID],
        [
            'a lowercase trace id next to a filter',
            null,
            { trace: LOWER_TRACE_ID, dateRange: JSON.stringify({ date_from: '-7d', date_to: null }) },
            UPPER_TRACE_ID,
        ],
        ['a trace id with path characters', UPPER_TRACE_ID, { trace: 'a/b' }, undefined],
    ])('cleans up %s in the URL without adding a back step', (_name, openTraceId, urlParams, expected) => {
        jest.spyOn(api.tracing, 'getTrace').mockResolvedValue({ results: [], hasMore: false })
        mountAt(openTraceId ? { trace: openTraceId } : {})
        router.actions.push('/tracing', urlParams)
        expect(router.values.searchParams.trace).toBe(expected)
        expect(router.values.lastMethod).toBe('REPLACE')
    })

    it.each([
        [
            'a lowercase span id with the trace',
            null,
            { trace: LOWER_TRACE_ID, span: '00f067aa0ba902b7' },
            '00F067AA0BA902B7',
        ],
        [
            'a lowercase span id in an open trace',
            UPPER_TRACE_ID,
            { trace: UPPER_TRACE_ID, span: '00f067aa0ba902b7' },
            '00F067AA0BA902B7',
        ],
        ['an AI span id', null, { trace: LOWER_TRACE_ID, span: 'ai:AbC-123' }, 'ai:AbC-123'],
    ])('selects %s from the URL in the case the trace API returns', (_name, openTraceId, urlParams, expected) => {
        jest.spyOn(api.tracing, 'getTrace').mockResolvedValue({ results: [], hasMore: false })
        mountAt(openTraceId ? { trace: openTraceId } : {})
        router.actions.push('/tracing', urlParams)
        expect(logic.values.selectedSpanId).toBe(expected)
    })

    it('opens a lowercase trace id from code only once', () => {
        const getTrace = jest.spyOn(api.tracing, 'getTrace').mockResolvedValue({ results: [], hasMore: false })
        mountAt({})
        logic.actions.openTrace(LOWER_TRACE_ID)
        expect(router.values.searchParams.trace).toBe(UPPER_TRACE_ID)
        expect(getTrace).toHaveBeenCalledTimes(1)
    })

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

    it.each([
        ['operations', FEATURE_FLAGS.TRACING_OPERATIONS_VIEW, undefined],
        ['endpoints', FEATURE_FLAGS.TRACING_ENDPOINTS_VIEW, true],
    ] as const)('opens the %s view from a deep link and fetches its aggregate', (view, flag, groupByEndpoint) => {
        const aggregate = jest.spyOn(api.tracing, 'aggregate')
        featureFlagLogic.actions.setFeatureFlags([], { [flag]: true })
        mountAt({ view })
        expect(logic.values.activeTracingTab).toBe(view)
        expect(aggregate).toHaveBeenLastCalledWith(
            expect.objectContaining({ groupByEndpoint, includeHealth: groupByEndpoint }),
            expect.anything()
        )
    })

    it.each(['operations', 'endpoints'])('ignores ?view=%s when its flag is off', (view) => {
        const filtersLogic = mountAt({ view })
        expect(logic.values.activeTracingTab).toBe('traces')
        expect(filtersLogic.values.viewMode).toBe('spans')
    })

    it('round-trips the non-default traces view mode through the URL', () => {
        const filtersLogic = mountAt({ view: 'traces' })
        expect(filtersLogic.values.viewMode).toBe('traces')
        expect(router.values.searchParams.view).toBe('traces')

        logic.actions.setDisplayMode('spans')
        expect(router.values.searchParams).not.toHaveProperty('view')
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

    it('refetches the Operations aggregation when the impact flag resolves late', () => {
        // Flags load asynchronously, so rows can arrive while the flag is still off. Without the
        // refetch the Sessions and Users columns render over rows that carry no impact fields.
        enableOperationsView()
        mountAt({ view: 'operations' })
        tracingDataLogic({ id: TRACING_SCENE_VIEWER_ID }).actions.fetchAggregationSuccess({
            current: [{ service_name: 'web', name: 'GET /', count: 1 }],
            previous: null,
        } as any)
        const aggregate = jest.spyOn(api.tracing, 'aggregate')

        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.TRACING_OPERATIONS_VIEW]: true,
            [FEATURE_FLAGS.TRACING_IMPACT_STRIP]: true,
        })

        expect(aggregate).toHaveBeenCalledWith(expect.objectContaining({ includeImpact: true }), expect.anything())
    })

    it('resets the operations tab to traces when the flag is disabled mid-session', () => {
        enableOperationsView()
        mountAt({ view: 'operations' })
        expect(logic.values.activeTracingTab).toBe('operations')

        featureFlagLogic.actions.setFeatureFlags([], {})
        expect(logic.values.activeTracingTab).toBe('traces')
        expect(logic.values.displayMode).toBe('spans')
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
        expect(router.values.searchParams).not.toHaveProperty('view')

        // Back/forward to a non-operations URL while on the operations tab resets the tab.
        logic.actions.setDisplayMode('operations')
        router.actions.push('/tracing', { view: 'spans' })
        expect(logic.values.activeTracingTab).toBe('traces')
        expect(logic.values.displayMode).toBe('spans')
    })

    it.each([
        ['already loaded', () => mountAt({ tab: 'sql', serviceNames: JSON.stringify(['checkout']) })],
        [
            'arriving after the URL parse',
            () => {
                featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_SCENE_TABS]: true })
                mountAt({ tab: 'sql', serviceNames: JSON.stringify(['checkout']) })
                featureFlagLogic.actions.setFeatureFlags([], {})
            },
        ],
    ])('drops a tab=sql deep link when the scene tabs flag is off, with flags %s', (_, mount) => {
        mount()
        expect(logic.values.sceneTab).toBe('viewer')
        expect(router.values.searchParams).not.toHaveProperty('tab')
        expect(router.values.searchParams.serviceNames).toEqual(['checkout'])
    })

    it('restores the SQL tab from a deep link without dropping the filter params', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_SCENE_TABS]: true })
        mountAt({ tab: 'sql', serviceNames: JSON.stringify(['checkout']) })
        expect(logic.values.activeSceneTab).toBe('sql')
        expect(router.values.searchParams).toMatchObject({ tab: 'sql', serviceNames: ['checkout'] })

        logic.actions.selectSceneTab('viewer')
        expect(router.values.searchParams).not.toHaveProperty('tab')
        expect(router.values.searchParams.serviceNames).toEqual(['checkout'])

        logic.actions.selectSceneTab('sql')
        featureFlagLogic.actions.setFeatureFlags([], {})
        expect(logic.values.activeSceneTab).toBe('viewer')
        expect(router.values.searchParams).not.toHaveProperty('tab')

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_SCENE_TABS]: true })
        expect(logic.values.activeSceneTab).toBe('viewer')
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

    it.each([
        ['a comparison window drag', 'drag'],
        ['a refresh', 'refresh'],
    ])('keeps endpoint grouping on the full range after %s while comparing', async (_label, trigger) => {
        silenceKeaLoadersErrors()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_ENDPOINTS_VIEW]: true })
        const filtersLogic = mountAt({ comparison: JSON.stringify({ mode: 'time', preset: 'custom' }) })
        expect(filtersLogic.values.compareActive).toBe(true)

        const aggregateSpy = jest.spyOn(api.tracing, 'aggregate')
        logic.actions.setActiveTracingTab('endpoints')
        await new Promise((resolve) => setTimeout(resolve, 0))
        aggregateSpy.mockClear()

        if (trigger === 'drag') {
            filtersLogic.actions.updateComparisonWindows({ startMs: 0, endMs: 1000 }, { startMs: 2000, endMs: 3000 })
        } else {
            logic.actions.refreshQuery()
        }
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(aggregateSpy).toHaveBeenLastCalledWith(
            expect.objectContaining({
                groupByEndpoint: true,
                compareFilter: expect.objectContaining({ compare: false }),
            }),
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
