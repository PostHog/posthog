import { router } from 'kea-router'

import api from 'lib/api'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { TRACING_SCENE_VIEWER_ID, tracingFiltersLogic } from './tracingFiltersLogic'
import { tracingSceneLogic } from './tracingSceneLogic'

describe('tracingSceneLogic', () => {
    let logic: ReturnType<typeof tracingSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
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

    // Guards the operations-tab rate denominator: on the operations tab the aggregate must always
    // cover the whole selected range (compare: false), even with a comparison active. A filter
    // change fires both the windowed aggregate (via runQuery) and the explicit full-range one, and
    // the full-range fetch must be the last one dispatched so it wins the abort race. Reorder those
    // two dispatches and the operations table would silently divide by the narrow compare sub-window.
    it('keeps the operations aggregate on the full range when a filter changes while comparing', async () => {
        silenceKeaLoadersErrors()
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
})
