import { router } from 'kea-router'

import api from 'lib/api'

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
})
