import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { makeSpan } from './__mocks__/span'
import { PREFETCH_SPANS, tracingDataLogic } from './tracingDataLogic'
import { tracingFiltersLogic } from './tracingFiltersLogic'
import { tracingViewerLogic } from './tracingViewerLogic'

describe('tracingViewerLogic', () => {
    let logic: ReturnType<typeof tracingViewerLogic.build>
    let getTraceSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        getTraceSpy = jest
            .spyOn(api.tracing, 'getTrace')
            .mockResolvedValue({ results: [], hasMore: false, nextOffset: null })
        logic = tracingViewerLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        getTraceSpy.mockRestore()
    })

    // The prefetch decision drives whether opening a trace refetches it by id: a partial
    // prefetch batch is the trace's complete span set (no fetch), while a cold link (zero
    // loaded spans) or a possibly-truncated full batch must fetch. Getting this wrong either
    // refetches every drawer open or shows truncated waterfalls on cold links.
    it.each([
        ['no loaded spans (cold link)', 0, true],
        ['a partial prefetch batch', 2, false],
        ['a possibly-truncated full batch', PREFETCH_SPANS, true],
    ])('openTrace with %s %s', (_name, spanCount, shouldFetch) => {
        const spans = Array.from({ length: spanCount }, (_, i) =>
            makeSpan({ uuid: `span-${i}`, span_id: `span-${i}`, trace_id: 'trace-x' })
        )
        tracingDataLogic().actions.fetchSpansSuccess(spans)

        logic.actions.openTrace('trace-x', { ts: '2024-01-01T00:00:00Z' })

        expect(logic.values.selectedTraceId).toBe('trace-x')
        expect(getTraceSpy.mock.calls.length > 0).toBe(shouldFetch)
    })

    describe('traceIdentity', () => {
        // The featureFlags reducer persists, so it survives initKeaTests. Each test sets the flag
        // it wants, otherwise a flag one test enables leaks into the next.
        beforeEach(() => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], {})
        })

        function enableCorrelationLinks(): void {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TRACING_SESSION_PERSON_LINKS], {
                [FEATURE_FLAGS.TRACING_SESSION_PERSON_LINKS]: true,
            })
        }

        // A partial prefetch batch is the trace's complete span set, so no fetch runs and the
        // identity resolves from it.
        function openCompleteTrace(attributes: Record<string, string>): void {
            tracingDataLogic().actions.fetchSpansSuccess([
                makeSpan({ uuid: 'span-0', span_id: 'span-0', trace_id: 'trace-x', attributes }),
                makeSpan({ uuid: 'span-1', span_id: 'span-1', trace_id: 'trace-x' }),
            ])
            logic.actions.openTrace('trace-x', { ts: '2024-01-01T00:00:00Z' })
        }

        it('resolves the person and session the open trace belongs to', () => {
            enableCorrelationLinks()

            openCompleteTrace({ posthogDistinctId: 'user-1', sessionId: 'session-1' })

            expect(logic.values.traceIdentity).toEqual({ distinctId: 'user-1', sessionId: 'session-1' })
        })

        it('resolves nothing while the flag is off', () => {
            openCompleteTrace({ posthogDistinctId: 'user-1', sessionId: 'session-1' })

            expect(logic.values.traceIdentity).toEqual({ distinctId: null, sessionId: null })
        })

        // "The spans disagree, so promote neither" can only be decided over the whole trace, so a
        // known-partial span set must resolve nothing rather than trust the page it has.
        it('resolves nothing while more spans can still load', async () => {
            enableCorrelationLinks()
            getTraceSpy.mockResolvedValue({
                results: [
                    makeSpan({
                        uuid: 'span-0',
                        span_id: 'span-0',
                        trace_id: 'trace-x',
                        attributes: { posthogDistinctId: 'user-1' },
                    }),
                ],
                hasMore: true,
                nextOffset: 1,
            })

            logic.actions.openTrace('trace-x', { ts: '2024-01-01T00:00:00Z' })
            await expectLogic(tracingDataLogic()).toFinishAllListeners()

            expect(logic.values.canLoadMoreTraceSpans).toBe(true)
            expect(logic.values.traceIdentity).toEqual({ distinctId: null, sessionId: null })
        })
    })

    describe('closeTrace', () => {
        // The attribute buttons in the drawer queue their query for when the drawer closes.
        // Without this, closing the drawer would silently drop the filter the user just added.
        it('flushes a filter refresh queued by the drawer buttons', async () => {
            tracingFiltersLogic().actions.addFilter('http.method', 'GET')
            expect(tracingFiltersLogic().values.hasDeferredFilterRefresh).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.closeTrace()
            }).toDispatchActions(['refreshDeferredFilters'])
        })

        it('does not dispatch a refresh when no filter was queued', async () => {
            expect(tracingFiltersLogic().values.hasDeferredFilterRefresh).toBe(false)

            await expectLogic(logic, () => {
                logic.actions.closeTrace()
            }).toNotHaveDispatchedActions(['refreshDeferredFilters'])
        })
    })
})
