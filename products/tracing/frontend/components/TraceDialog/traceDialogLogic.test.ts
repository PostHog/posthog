import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { logsViewerModalLogic } from 'products/logs/frontend/components/LogsViewer/LogsViewerModal/logsViewerModalLogic'
import type { Span } from 'products/tracing/frontend/types'

import { traceViewLogic } from '../TraceView/traceViewLogic'
import { TRACE_DIALOG_VIEW_ID, traceDialogLogic } from './traceDialogLogic'

type TracePage = Awaited<ReturnType<typeof api.tracing.getTrace>>

function span(spanId: string, statusCode = 0): Span {
    return {
        uuid: spanId,
        trace_id: 'abc123',
        span_id: spanId,
        parent_span_id: '',
        name: spanId,
        kind: 0,
        service_name: 'agent-worker',
        status_code: statusCode,
        timestamp: '2026-10-14T10:00:00.000000Z',
        end_time: '2026-10-14T10:00:01.000000Z',
        duration_nano: 1_000_000_000,
        is_root_span: false,
        matched_filter: true,
        attributes: {},
        resource_attributes: {},
    }
}

function page(spanIds: string[], nextOffset: number | null): TracePage {
    return { results: spanIds.map(span), hasMore: nextOffset != null, nextOffset }
}

describe('traceDialogLogic', () => {
    let logic: ReturnType<typeof traceDialogLogic.build>
    let view: ReturnType<typeof traceViewLogic.build>
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
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.TRACING_SPAN_ERROR_BADGES]: true,
            [FEATURE_FLAGS.TRACING_SESSION_PERSON_LINKS]: true,
        })
        getTraceSpy = jest.spyOn(api.tracing, 'getTrace').mockResolvedValue(page(['a'], null))
        router.actions.push('/logs')
        logic = traceDialogLogic()
        logic.mount()
        view = traceViewLogic({ id: TRACE_DIALOG_VIEW_ID })
    })

    afterEach(() => {
        logic.unmount()
        getTraceSpy.mockRestore()
    })

    it('keeps the trace after close so the exit animation does not flash an empty dialog', async () => {
        logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'def456' }, { entryPoint: 'log_details' })

        await expectLogic(logic, () => {
            logic.actions.closeTraceDialog()
        }).toMatchValues({ isOpen: false, trace: { traceId: 'abc123', spanId: 'DEF456' } })
    })

    it.each([
        ['stays open on a query-only change', '/logs?filters=abc', true],
        ['stays open on a hash-only change', '/logs#panel', true],
        ['closes on a new pathname', '/insights', false],
    ])('%s', async (_name, url, expectedOpen) => {
        logic.actions.openTraceDialog({ traceId: 'abc123' }, { entryPoint: 'log_details' })

        await expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ isOpen: expectedOpen })
    })

    it.each([
        ['an id in the API case', 'B1'],
        // Logs carry lowercase hex, and the trace API returns uppercase.
        ['a lowercase hex id from a log', 'b1'],
    ])('selects the span the dialog was opened from, given %s', async (_name, openedSpanId) => {
        getTraceSpy.mockResolvedValueOnce({ results: [span('A1'), span('B1')], hasMore: false, nextOffset: null })

        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: openedSpanId }, { entryPoint: 'log_details' })
        }).toDispatchActions(['loadTraceSpansSuccess'])

        expect(view.values.selectedSpan?.span_id).toBe('B1')
    })

    it.each([
        // An overlapping page adds nothing, so paging on would spin forever on the same spans.
        ['stops when a page adds no new span', [page(['a', 'b'], 2), page(['a', 'b'], 4)], ['a', 'b'], false, 2],
        [
            'marks the trace truncated at the page cap',
            Array.from({ length: 6 }, (_, i) => page([`s${i}`], i + 1)),
            ['s0', 's1', 's2', 's3', 's4'],
            true,
            5,
        ],
    ])('%s', async (_name, pages, expectedSpanIds, expectedTruncated, expectedCalls) => {
        pages.forEach((p) => getTraceSpy.mockResolvedValueOnce(p))

        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'abc123' }, { entryPoint: 'log_details' })
        }).toDispatchActions(['loadTraceSpansSuccess'])

        expect(logic.values.traceSpans?.spans.map((s) => s.span_id)).toEqual(expectedSpanIds)
        expect(logic.values.traceSpans?.truncated).toBe(expectedTruncated)
        expect(getTraceSpy).toHaveBeenCalledTimes(expectedCalls)
    })

    it('stops paging once the dialog closes', async () => {
        let resolveFirstPage: (p: TracePage) => void = () => {}
        getTraceSpy.mockReturnValueOnce(new Promise<TracePage>((resolve) => (resolveFirstPage = resolve)))

        logic.actions.openTraceDialog({ traceId: 'abc123' }, { entryPoint: 'log_details' })
        logic.actions.closeTraceDialog()
        await expectLogic(logic, () => {
            resolveFirstPage(page(['a'], 1))
        }).toDispatchActions(['loadTraceSpansSuccess'])

        expect(getTraceSpy).toHaveBeenCalledTimes(1)
    })

    it('ignores a failure from a trace that a newer one replaced', async () => {
        let rejectFirstTrace: (error: Error) => void = () => {}
        getTraceSpy.mockReturnValueOnce(new Promise<TracePage>((_, reject) => (rejectFirstTrace = reject)))

        logic.actions.openTraceDialog({ traceId: 'first' }, { entryPoint: 'log_details' })
        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'second' }, { entryPoint: 'log_details' })
        }).toDispatchActions(['loadTraceSpansSuccess'])

        rejectFirstTrace(new Error('boom'))
        await expectLogic(logic)
            .toNotHaveDispatchedActions(['loadTraceSpansFailure'])
            .toMatchValues({ traceSpansFailed: false })
    })

    it('selects a span when collapsing it hides the selection, and lists only spans on screen', async () => {
        const child = (spanId: string, parentSpanId: string): Span => ({
            ...span(spanId),
            parent_span_id: parentSpanId,
        })
        getTraceSpy.mockResolvedValueOnce({
            results: [{ ...span('ROOT'), is_root_span: true }, child('A', 'ROOT'), child('A1', 'A')],
            hasMore: false,
            nextOffset: null,
        })
        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'A1' }, { entryPoint: 'log_details' })
        }).toDispatchActions(['loadTraceSpansSuccess'])

        logic.actions.toggleSpanCollapsed('A')

        expect(view.values.selectedSpanId).toBe('A')
        expect(view.values.flatSpans.map((node) => node.span.span_id)).toEqual(['ROOT', 'A'])
    })

    it('clears the failure once a retry succeeds', async () => {
        getTraceSpy.mockRejectedValueOnce(new Error('boom'))
        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'abc123' }, { entryPoint: 'log_details' })
        })
            .toDispatchActions(['loadTraceSpansFailure'])
            .toMatchValues({ traceSpansFailed: true })

        await expectLogic(logic, () => {
            logic.actions.loadTraceSpans({ traceId: 'abc123' })
        })
            .toDispatchActions(['loadTraceSpansSuccess'])
            .toMatchValues({ traceSpansFailed: false })
    })

    it.each([
        ['leads with errors on an error span', 2, 'errors'],
        ['leads with logs on any other span', 0, 'logs'],
    ])('%s', async (_name, statusCode, expectedTab) => {
        getTraceSpy.mockResolvedValueOnce({ results: [span('a', statusCode)], hasMore: false, nextOffset: null })

        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'a' }, { entryPoint: 'log_details' })
        }).toDispatchActions(['loadTraceSpansSuccess'])
        expect(view.values.activeInspectorTab).toBe(expectedTab)
    })

    it('keeps a picked tab across spans, and drops it for the next trace', async () => {
        getTraceSpy.mockResolvedValue({ results: [span('a', 2), span('b')], hasMore: false, nextOffset: null })
        logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'a' }, { entryPoint: 'log_details' })
        await expectLogic(logic).toDispatchActions(['loadTraceSpansSuccess'])

        logic.actions.setInspectorTab('attributes')
        logic.actions.selectSpan('b')
        expect(view.values.activeInspectorTab).toBe('attributes')

        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'def456', spanId: 'a' }, { entryPoint: 'log_details' })
        }).toDispatchActions(['loadTraceSpansSuccess'])
        expect(view.values.activeInspectorTab).toBe('errors')
    })

    it('treats a missing parent row as its own selection, not the root span', async () => {
        const orphan = { ...span('child'), parent_span_id: 'GONE' }
        getTraceSpy.mockResolvedValueOnce({ results: [span('a'), orphan], hasMore: false, nextOffset: null })
        logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'a' }, { entryPoint: 'log_details' })
        await expectLogic(logic).toDispatchActions(['loadTraceSpansSuccess'])

        logic.actions.selectSpan('GONE')
        expect(view.values.missingParentSpanId).toBe('GONE')

        logic.actions.selectSpan('child')
        expect(view.values.missingParentSpanId).toBeNull()
    })

    it.each([
        ['a recording opens', () => sessionPlayerModalLogic.actions.openSessionPlayer({ id: 'session-1' })],
        ['the full-screen logs viewer opens', () => logsViewerModalLogic.actions.openLogsViewerModal()],
    ])('closes when %s, since that modal sits behind the dialog', async (_name, open) => {
        logic.actions.openTraceDialog({ traceId: 'abc123' }, { entryPoint: 'log_details' })

        await expectLogic(logic, open).toMatchValues({ isOpen: false })
    })

    it('drops the log from a previous open, so a later open has no stale strip or marker', async () => {
        logic.actions.openTraceDialog(
            { traceId: 'abc123', ts: '2026-05-01T12:00:00.000Z' },
            { entryPoint: 'log_details', openedFrom: { body: 'run_sql failed', severity: 'error' } }
        )
        expect(logic.values.openedAtUs).not.toBeNull()

        // A metrics link passes a time near the trace, which is no point in it to mark.
        await expectLogic(logic, () => {
            logic.actions.openTraceDialog(
                { traceId: 'def456', ts: '2026-05-01T12:00:00.000Z' },
                { entryPoint: 'metric_exemplar' }
            )
        }).toMatchValues({ openedFrom: null, openedAtUs: null })
    })

    describe('span keys', () => {
        let pageListener: jest.Mock

        beforeEach(async () => {
            getTraceSpy.mockResolvedValue({ results: [span('a'), span('b')], hasMore: false, nextOffset: null })
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'a' }, { entryPoint: 'log_details' })
            await expectLogic(logic).toDispatchActions(['loadTraceSpansSuccess'])
            // Stands in for the logs list under the dialog, which binds J and K on window too.
            pageListener = jest.fn()
            window.addEventListener('keydown', pageListener)
        })

        afterEach(() => {
            window.removeEventListener('keydown', pageListener)
        })

        const press = (key: string, target: EventTarget = document.body): void => {
            target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
        }

        it('steps through spans and keeps the key from the page under the dialog', () => {
            press('j')
            expect(view.values.selectedSpan?.span_id).toBe('b')
            press('k')
            expect(view.values.selectedSpan?.span_id).toBe('a')
            expect(pageListener).not.toHaveBeenCalled()
        })

        it('collapses, climbs and expands with the arrow keys', async () => {
            const child = (spanId: string, parentSpanId: string): Span => ({
                ...span(spanId),
                parent_span_id: parentSpanId,
            })
            getTraceSpy.mockResolvedValue({
                results: [{ ...span('ROOT'), is_root_span: true }, child('A', 'ROOT'), child('A1', 'A')],
                hasMore: false,
                nextOffset: null,
            })
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'A1' }, { entryPoint: 'log_details' })
            await expectLogic(logic).toDispatchActions(['loadTraceSpansSuccess'])
            const visible = (): string[] => view.values.flatSpans.map((node) => node.span.span_id)

            // A1 has nothing to collapse, so left climbs to A, then collapses A.
            press('ArrowLeft')
            expect(view.values.selectedSpanId).toBe('A')
            press('ArrowLeft')
            expect(visible()).toEqual(['ROOT', 'A'])

            // Right reopens A, then steps into its child.
            press('ArrowRight')
            expect(visible()).toEqual(['ROOT', 'A', 'A1'])
            press('ArrowRight')
            expect(view.values.selectedSpanId).toBe('A1')
            expect(pageListener).not.toHaveBeenCalled()
        })

        it('opens a folded chain with the right arrow, and keeps the selection on screen when it folds again', async () => {
            const child = (spanId: string, parentSpanId: string): Span => ({
                ...span(spanId),
                parent_span_id: parentSpanId,
            })
            getTraceSpy.mockResolvedValue({
                results: [
                    { ...span('ROOT'), is_root_span: true },
                    child('A', 'ROOT'),
                    child('B', 'A'),
                    child('C', 'B'),
                    child('LEAF', 'C'),
                ],
                hasMore: false,
                nextOffset: null,
            })
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'ROOT' }, { entryPoint: 'log_details' })
            await expectLogic(logic).toDispatchActions(['loadTraceSpansSuccess'])
            const visible = (): string[] => view.values.flatSpans.map((node) => node.span.span_id)
            expect(visible()).toEqual(['ROOT', 'A', 'LEAF'])

            logic.actions.selectSpan('A')
            press('ArrowRight')
            expect(visible()).toEqual(['ROOT', 'A', 'B', 'C', 'LEAF'])

            logic.actions.selectSpan('C')
            logic.actions.toggleChain('A')
            expect(view.values.selectedSpanId).toBe('A')
        })

        it('steps onto a missing parent row and on past it', async () => {
            const orphan = { ...span('b'), parent_span_id: 'GONE' }
            getTraceSpy.mockResolvedValue({ results: [span('a'), orphan], hasMore: false, nextOffset: null })
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'a' }, { entryPoint: 'log_details' })
            await expectLogic(logic).toDispatchActions(['loadTraceSpansSuccess'])

            press('j')
            expect(view.values.missingParentSpanId).toBe('GONE')
            press('j')
            expect(view.values.missingParentSpanId).toBeNull()
            expect(view.values.selectedSpan?.span_id).toBe('b')
            press('k')
            expect(view.values.missingParentSpanId).toBe('GONE')
            press('k')
            expect(view.values.selectedSpan?.span_id).toBe('a')
        })

        it('leaves keys typed into an input in the dialog alone, but not one hidden behind it', () => {
            const dialog = document.createElement('div')
            dialog.setAttribute('data-attr', 'trace-dialog')
            const inDialog = document.createElement('input')
            const behind = document.createElement('textarea')
            dialog.appendChild(inDialog)
            document.body.append(dialog, behind)

            press('j', inDialog)
            expect(view.values.selectedSpan?.span_id).toBe('a')
            expect(pageListener).toHaveBeenCalledTimes(1)

            press('j', behind)
            expect(view.values.selectedSpan?.span_id).toBe('b')
            expect(pageListener).toHaveBeenCalledTimes(1)
            dialog.remove()
            behind.remove()
        })

        it('stops listening once the dialog closes', () => {
            logic.actions.closeTraceDialog()
            press('j')

            expect(view.values.selectedSpan?.span_id).toBe('a')
            expect(pageListener).toHaveBeenCalledTimes(1)
        })
    })

    it.each([
        ['names the person and session of a complete trace', 1, { distinctId: 'person-1', sessionId: 'session-1' }],
        // A later page could carry a second person, so a truncated trace names no one.
        ['names no one when the trace is truncated', 6, { distinctId: null, sessionId: null }],
    ])('%s', async (_name, pageCount, expectedIdentity) => {
        for (let i = 0; i < pageCount; i++) {
            const identified = {
                ...span(`s${i}`),
                attributes: { posthogDistinctId: 'person-1', sessionId: 'session-1' },
            }
            getTraceSpy.mockResolvedValueOnce({
                results: [identified],
                hasMore: i < pageCount - 1,
                nextOffset: i < pageCount - 1 ? i + 1 : null,
            })
        }

        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'abc123' }, { entryPoint: 'log_details' })
        })
            .toDispatchActions(['loadTraceSpansSuccess'])
            .toMatchValues({ traceIdentity: expectedIdentity })
    })

    describe('usage events', () => {
        let captureSpy: jest.SpyInstance

        beforeEach(() => {
            captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        })

        afterEach(() => {
            captureSpy.mockRestore()
        })

        const closeReasons = (): string[] =>
            captureSpy.mock.calls
                .filter(([event]) => event === 'tracing trace dialog closed')
                .map(([, properties]) => properties.reason)

        it.each([
            ['dismissed', () => logic.actions.closeTraceDialog(), ['dismissed']],
            ['back to log', () => logic.actions.closeTraceDialog('back_to_log'), ['back_to_log']],
            ['navigated away', () => router.actions.push('/insights'), ['navigated']],
            // The Open in Tracing link navigates too, but the close has to say why.
            [
                'open in tracing',
                () => {
                    logic.actions.openInTracing()
                    router.actions.push('/tracing')
                },
                ['open_in_tracing'],
            ],
            [
                'open in tracing without a pathname change',
                () => {
                    logic.actions.openInTracing()
                    router.actions.push(router.values.location.pathname, { trace: 'abc123' })
                    expect(logic.values.isOpen).toBe(false)
                },
                ['open_in_tracing'],
            ],
            [
                'another trace opened over it',
                () => logic.actions.openTraceDialog({ traceId: 'def456' }, { entryPoint: 'metric_sample' }),
                // The second dialog closes on the final dismiss.
                ['replaced', 'dismissed'],
            ],
        ])('records one close for %s', async (_name, exit, expectedReasons) => {
            logic.actions.openTraceDialog({ traceId: 'abc123' }, { entryPoint: 'log_details' })
            await expectLogic(logic).toDispatchActions(['loadTraceSpansSuccess'])

            exit()
            // A second close of an already-closed dialog must not record another session.
            logic.actions.closeTraceDialog()

            expect(closeReasons()).toEqual(expectedReasons)
        })

        it('reports the entry point and how the person moved through the trace', async () => {
            getTraceSpy.mockResolvedValue({ results: [span('a'), span('b')], hasMore: false, nextOffset: null })
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'a' }, { entryPoint: 'log_row_action' })
            await expectLogic(logic).toDispatchActions(['loadTraceSpansSuccess'])

            logic.actions.selectNextSpan()
            logic.actions.setInspectorTab('attributes')
            logic.actions.toggleSpanCollapsed('a')
            logic.actions.closeTraceDialog()

            expect(captureSpy).toHaveBeenCalledWith('tracing trace dialog opened', {
                entry_point: 'log_row_action',
                has_span: true,
                has_log: false,
            })
            expect(captureSpy).toHaveBeenCalledWith(
                'tracing trace dialog closed',
                expect.objectContaining({
                    entry_point: 'log_row_action',
                    reason: 'dismissed',
                    spans_selected: 1,
                    keyboard_steps: 1,
                    collapse_toggles: 1,
                    tabs_viewed: ['attributes'],
                })
            )
        })
    })
})
