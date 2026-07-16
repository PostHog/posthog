import { router } from 'kea-router'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { tracingOperationSceneLogic } from './tracingOperationSceneLogic'
import type { Span } from './types'

const createMockSample = (n: number): Span => ({
    uuid: `uuid-${n}`,
    trace_id: `trace-${n}`,
    span_id: `span-${n}`,
    parent_span_id: 'parent',
    name: 'db query',
    kind: 3,
    service_name: 'web',
    status_code: 1,
    timestamp: `2024-01-01T0${n}:00:00Z`,
    end_time: `2024-01-01T0${n}:00:01Z`,
    duration_nano: 1_000_000_000,
    is_root_span: false,
    matched_filter: true,
    attributes: {},
    resource_attributes: {},
})

describe('tracingOperationSceneLogic', () => {
    let logic: ReturnType<typeof tracingOperationSceneLogic.build>
    let listSpansSpy: jest.SpyInstance
    let getTraceSpy: jest.SpyInstance

    beforeEach(async () => {
        initKeaTests()
        jest.spyOn(api.tracing, 'durationHistogram').mockResolvedValue({ results: [] })
        jest.spyOn(api.tracing, 'aggregate').mockResolvedValue({ results: [] })
        listSpansSpy = jest.spyOn(api.tracing, 'listSpans').mockResolvedValue({ results: [], hasMore: false })
        getTraceSpy = jest.spyOn(api.tracing, 'getTrace').mockResolvedValue({ results: [], hasMore: false })
        logic = tracingOperationSceneLogic({ serviceName: 'web', spanName: 'db query' })
        logic.mount()
        // Settle the mount-time fetches (these calls supersede them via the loader breakpoint),
        // so their empty results can't land mid-test and clobber seeded samples.
        await Promise.all([
            logic.asyncActions.fetchHistogram(),
            logic.asyncActions.fetchStats(),
            logic.asyncActions.fetchSamples(),
        ])
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('drag-selecting a duration range refetches samples scoped to the range and resets the pager', async () => {
        logic.actions.fetchSamplesSuccess([1, 2, 3, 4].map(createMockSample))
        logic.actions.setSampleIndex(3)

        logic.actions.setDurationSelection({ minNs: 5_000_000, maxNs: 10_000_000 })
        // The listener wiring dispatches the refetch synchronously, and the pager resets with it.
        expect(logic.values.samplesLoading).toBe(true)
        expect(logic.values.sampleIndex).toBe(0)

        await logic.asyncActions.fetchSamples()
        expect(listSpansSpy).toHaveBeenLastCalledWith(
            expect.objectContaining({
                flatSpans: true,
                serviceNames: ['web'],
                filterGroup: {
                    type: 'AND',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                { type: 'span', key: 'name', operator: 'exact', value: ['db query'] },
                                // The span duration filter's unit is ms; the range above is 5–10ms in ns.
                                { type: 'span', key: 'duration', operator: 'gte', value: 5 },
                                { type: 'span', key: 'duration', operator: 'lt', value: 10 },
                            ],
                        },
                    ],
                },
            })
        )
    })

    it('paging to another sample fetches its containing trace and anchors the waterfall on the sample span', async () => {
        logic.actions.fetchSamplesSuccess([1, 2].map(createMockSample))

        logic.actions.setSampleIndex(1)
        expect(logic.values.sampleTraceSpansLoading).toBe(true)

        await logic.asyncActions.fetchSampleTrace({ sample: logic.values.currentSample! })
        expect(getTraceSpy).toHaveBeenLastCalledWith('trace-2', expect.anything())
        expect(logic.values.selectedSpanId).toBe('span-2')
    })

    it('ignores a negative sample index restored from the URL', () => {
        router.actions.push('/tracing/operation', { sample: '-1' })
        expect(logic.values.sampleIndex).toBe(0)
    })
})
