import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { logsViewerModalLogic } from 'products/logs/frontend/components/LogsViewer/LogsViewerModal/logsViewerModalLogic'

import { makeSpan } from './__mocks__/span'
import { traceViewLogic } from './components/TraceView/traceViewLogic'
import { PREFETCH_SPANS, tracingDataLogic } from './tracingDataLogic'
import { tracingFiltersLogic } from './tracingFiltersLogic'
import { traceViewId, tracingViewerLogic } from './tracingViewerLogic'

describe('tracingViewerLogic', () => {
    let logic: ReturnType<typeof tracingViewerLogic.build>
    let getTraceSpy: jest.SpyInstance

    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.ErrorTracking]: AccessControlLevel.Viewer,
            },
        } as AppContext
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
    // prefetch batch with its root is the trace's complete span set (no fetch), while a cold link
    // (zero loaded spans), an orphan batch (no root span), or a possibly-truncated full batch must
    // fetch. Getting this wrong either refetches every drawer open or shows truncated waterfalls.
    it.each([
        ['no loaded spans (cold link)', 0, true, true],
        ['a partial prefetch batch', 2, true, false],
        ['a partial prefetch batch with no root span (orphan)', 2, false, true],
        ['a possibly-truncated full batch', PREFETCH_SPANS, true, true],
    ])('openTrace with %s', (_name, spanCount, hasRoot, shouldFetch) => {
        const spans = Array.from({ length: spanCount }, (_, i) =>
            makeSpan({ uuid: `span-${i}`, span_id: `span-${i}`, trace_id: 'trace-x', is_root_span: hasRoot && i === 0 })
        )
        tracingDataLogic().actions.fetchSpansSuccess(spans)

        logic.actions.openTrace('trace-x', { ts: '2024-01-01T00:00:00Z' })

        expect(logic.values.selectedTraceId).toBe('trace-x')
        expect(getTraceSpy.mock.calls.length > 0).toBe(shouldFetch)
    })

    it("does not carry a previous trace's load failure into a trace opened from a complete prefetch", () => {
        logic.actions.openTrace('trace-a', { ts: '2024-01-01T00:00:00Z' })
        tracingDataLogic().actions.loadTraceSpansFailure('boom')
        expect(logic.values.traceSpansLoadFailed).toBe(true)

        const spans = [makeSpan({ uuid: 'span-0', span_id: 'span-0', trace_id: 'trace-b', is_root_span: true })]
        tracingDataLogic().actions.fetchSpansSuccess(spans)
        logic.actions.openTrace('trace-b', { ts: '2024-01-01T00:00:00Z' })

        expect(logic.values.selectedTraceId).toBe('trace-b')
        expect(logic.values.traceSpansLoadFailed).toBe(true)
        expect(logic.values.selectedTraceLoadFailed).toBe(false)
    })

    // A full fetch can fail, then a later list refresh prefetch the same trace complete (root span,
    // under the cap). Reopening it skips the fetch and must not read the earlier attempt's failure.
    it("does not carry a trace's own previous load failure into its reopen from a complete prefetch", () => {
        logic.actions.openTrace('trace-a', { ts: '2024-01-01T00:00:00Z' })
        tracingDataLogic().actions.loadTraceSpansFailure('boom')
        expect(logic.values.selectedTraceLoadFailed).toBe(true)
        logic.actions.closeTrace()

        const spans = [makeSpan({ uuid: 'span-0', span_id: 'span-0', trace_id: 'trace-a', is_root_span: true })]
        tracingDataLogic().actions.fetchSpansSuccess(spans)
        logic.actions.openTrace('trace-a', { ts: '2024-01-01T00:00:00Z' })

        expect(logic.values.selectedTraceId).toBe('trace-a')
        expect(getTraceSpy).toHaveBeenCalledTimes(1)
        expect(logic.values.selectedTraceLoadFailed).toBe(false)
    })

    // Without a ts hint the lookup must not fall back to a date window, or a trace older than that
    // window never loads. With a hint, the lookup stays bounded to the hint's narrow window, and
    // retries by id alone when the hint sits too far from the spans to find any.
    const hintWindow = { date_from: '2023-12-31T23:00:00.000Z', date_to: '2024-01-01T01:00:00.000Z' }
    it.each([
        ['a ts hint that finds spans', '2024-01-01T00:00:00Z', true, [hintWindow], 1],
        ['a ts hint that finds no spans', '2024-01-01T00:00:00Z', false, [hintWindow, undefined], 1],
        ['no ts hint', undefined, false, [undefined], 0],
    ])('openTrace with %s sends the matching date ranges', async (_name, ts, firstFindsSpans, dateRanges, loaded) => {
        const span = makeSpan({ uuid: 'span-0', span_id: 'span-0', trace_id: 'trace-x', is_root_span: true })
        getTraceSpy
            .mockResolvedValueOnce({ results: firstFindsSpans ? [span] : [], hasMore: false, nextOffset: null })
            .mockResolvedValueOnce({ results: [span], hasMore: false, nextOffset: null })

        await expectLogic(logic, () => logic.actions.openTrace('trace-x', { ts })).toFinishAllListeners()

        expect(getTraceSpy.mock.calls.map(([, params]) => params.dateRange)).toEqual(dateRanges)
        expect(tracingDataLogic().values.traceSpans).toHaveLength(loaded)
    })

    describe('identity resolution', () => {
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

        // The Errors tab needs the session without the person, so it follows the error badge flag.
        // Reading the person flag instead would leave the tab empty on a team that has only badges.
        it.each([
            ['the error badge flag', FEATURE_FLAGS.TRACING_SPAN_ERROR_BADGES, 'session-1'],
            ['the person and replay flag', FEATURE_FLAGS.TRACING_SESSION_PERSON_LINKS, null],
        ])('resolves traceSessionId under %s', (_name, flag, expected) => {
            featureFlagLogic.actions.setFeatureFlags([flag], { [flag]: true })

            openCompleteTrace({ posthogDistinctId: 'user-1', sessionId: 'session-1' })

            expect(logic.values.traceSessionId).toBe(expected)
        })

        // A badge sits on one row and resolves that row's session. A trace touching two sessions
        // must therefore still answer for the row the badge opened, or clicking a row that just
        // showed a count lands on a tab saying the trace has no session. The full-trace fetch
        // returns the earliest page of a large trace, so the anchored row can be missing from it
        // while it still sits in the list the badge was clicked in.
        it.each([
            ['the prefetched list', false],
            ['the list when the fetched trace page omits it', true],
        ])('resolves traceSessionId from the anchored span in %s', (_name, tracePageOmitsAnchor) => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TRACING_SPAN_ERROR_BADGES], {
                [FEATURE_FLAGS.TRACING_SPAN_ERROR_BADGES]: true,
            })
            const spanA = makeSpan({
                uuid: 'span-0',
                span_id: 'span-0',
                trace_id: 'trace-x',
                attributes: { sessionId: 'a' },
            })
            const spanB = makeSpan({
                uuid: 'span-1',
                span_id: 'span-1',
                trace_id: 'trace-x',
                attributes: { sessionId: 'b' },
            })
            tracingDataLogic().actions.fetchSpansSuccess([spanA, spanB])

            logic.actions.openTrace('trace-x', { spanId: 'span-1', ts: '2024-01-01T00:00:00Z' })
            if (tracePageOmitsAnchor) {
                tracingDataLogic().actions.loadTraceSpansSuccess([spanA])
            }

            expect(logic.values.traceSessionId).toBe('b')
        })
    })

    // The drawer stays mounted from one row to the next, so a person reading the Logs tab row by
    // row must not be bounced back to Attributes on every click.
    it('keeps the inspector tab across traces while the drawer is open, and resets it on close', () => {
        const view = traceViewLogic({ id: traceViewId('default') })
        logic.actions.openTrace('trace-x')
        expect(view.values.activeInspectorTab).toBe('attributes')
        view.actions.setInspectorTab('logs')

        logic.actions.openTrace('trace-y')
        expect(view.values.activeInspectorTab).toBe('logs')

        logic.actions.openTrace('trace-z', { tab: 'errors' })
        expect(view.values.activeInspectorTab).toBe('errors')

        logic.actions.closeTrace()
        logic.actions.openTrace('trace-x')
        expect(view.values.activeInspectorTab).toBe('attributes')
    })

    // The URL carries the selected span, so a click in the tree and a span from the URL must each reach the other.
    it('keeps the selected span in step between the URL and the span tree', () => {
        const view = traceViewLogic({ id: traceViewId('default') })
        logic.actions.openTrace('trace-x', { spanId: 'aa01' })
        expect(view.values.selectedSpanId).toBe('AA01')

        view.actions.selectSpan('BB02')
        expect(logic.values.selectedSpanId).toBe('BB02')

        logic.actions.selectSpan('cc03')
        expect(view.values.selectedSpanId).toBe('CC03')

        logic.actions.selectSpan(null)
        expect(view.values.selectedSpanId).toBeNull()
    })

    it('steps through spans with J only while the drawer is open', () => {
        const view = traceViewLogic({ id: traceViewId('default') })
        const press = (): void => {
            document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true }))
        }
        logic.actions.openTrace('trace-x', { spanId: 'aa01' })
        view.actions.setSpans([
            makeSpan({ uuid: 'AA01', span_id: 'AA01', trace_id: 'trace-x' }),
            makeSpan({ uuid: 'BB02', span_id: 'BB02', trace_id: 'trace-x' }),
        ])

        press()
        expect(logic.values.selectedSpanId).toBe('BB02')

        logic.actions.closeTrace()
        view.actions.selectSpan('AA01')
        press()
        expect(view.values.selectedSpanId).toBe('AA01')
    })

    it('leaves J to the full-screen logs viewer while it is open over the drawer', () => {
        const view = traceViewLogic({ id: traceViewId('default') })
        const press = (): void => {
            document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true }))
        }
        logic.actions.openTrace('trace-x', { spanId: 'aa01' })
        view.actions.setSpans([
            makeSpan({ uuid: 'AA01', span_id: 'AA01', trace_id: 'trace-x' }),
            makeSpan({ uuid: 'BB02', span_id: 'BB02', trace_id: 'trace-x' }),
        ])

        logsViewerModalLogic.actions.openLogsViewerModal()
        press()
        expect(view.values.selectedSpanId).toBe('AA01')

        logsViewerModalLogic.actions.closeLogsViewerModal()
        press()
        expect(view.values.selectedSpanId).toBe('BB02')
    })

    it('steps only the most recently opened view when two have span keys', () => {
        const view = traceViewLogic({ id: traceViewId('default') })
        const overlay = traceViewLogic({ id: 'overlay' })
        overlay.mount()
        const press = (): void => {
            document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true }))
        }
        logic.actions.openTrace('trace-x', { spanId: 'aa01' })
        view.actions.setSpans([
            makeSpan({ uuid: 'AA01', span_id: 'AA01', trace_id: 'trace-x' }),
            makeSpan({ uuid: 'BB02', span_id: 'BB02', trace_id: 'trace-x' }),
        ])
        overlay.actions.showTrace('CC01', null)
        overlay.actions.setSpans([
            makeSpan({ uuid: 'CC01', span_id: 'CC01', trace_id: 'trace-y' }),
            makeSpan({ uuid: 'DD02', span_id: 'DD02', trace_id: 'trace-y' }),
        ])
        overlay.actions.enableSpanKeys('[data-attr="overlay"]')

        press()
        expect(overlay.values.selectedSpanId).toBe('DD02')
        expect(view.values.selectedSpanId).toBe('AA01')

        overlay.actions.disableSpanKeys()
        press()
        expect(view.values.selectedSpanId).toBe('BB02')
        overlay.unmount()
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
