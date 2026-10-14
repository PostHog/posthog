import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import type { Span } from 'products/tracing/frontend/types'

import { traceDialogLogic } from './traceDialogLogic'

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
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_SPAN_ERROR_BADGES]: true })
        getTraceSpy = jest.spyOn(api.tracing, 'getTrace').mockResolvedValue(page(['a'], null))
        router.actions.push('/logs')
        logic = traceDialogLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        getTraceSpy.mockRestore()
    })

    it('keeps the trace after close so the exit animation does not flash an empty dialog', async () => {
        logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'def456' })

        await expectLogic(logic, () => {
            logic.actions.closeTraceDialog()
        }).toMatchValues({ isOpen: false, trace: { traceId: 'abc123', spanId: 'DEF456' } })
    })

    it.each([
        ['stays open on a query-only change', '/logs?filters=abc', true],
        ['stays open on a hash-only change', '/logs#panel', true],
        ['closes on a new pathname', '/insights', false],
    ])('%s', async (_name, url, expectedOpen) => {
        logic.actions.openTraceDialog({ traceId: 'abc123' })

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
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: openedSpanId })
        }).toDispatchActions(['loadTraceSpansSuccess'])

        expect(logic.values.selectedSpanId).toBe('B1')
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
            logic.actions.openTraceDialog({ traceId: 'abc123' })
        }).toDispatchActions(['loadTraceSpansSuccess'])

        expect(logic.values.traceSpans?.spans.map((s) => s.span_id)).toEqual(expectedSpanIds)
        expect(logic.values.traceSpans?.truncated).toBe(expectedTruncated)
        expect(getTraceSpy).toHaveBeenCalledTimes(expectedCalls)
    })

    it('stops paging once the dialog closes', async () => {
        let resolveFirstPage: (p: TracePage) => void = () => {}
        getTraceSpy.mockReturnValueOnce(new Promise<TracePage>((resolve) => (resolveFirstPage = resolve)))

        logic.actions.openTraceDialog({ traceId: 'abc123' })
        logic.actions.closeTraceDialog()
        await expectLogic(logic, () => {
            resolveFirstPage(page(['a'], 1))
        }).toDispatchActions(['loadTraceSpansSuccess'])

        expect(getTraceSpy).toHaveBeenCalledTimes(1)
    })

    it('ignores a failure from a trace that a newer one replaced', async () => {
        let rejectFirstTrace: (error: Error) => void = () => {}
        getTraceSpy.mockReturnValueOnce(new Promise<TracePage>((_, reject) => (rejectFirstTrace = reject)))

        logic.actions.openTraceDialog({ traceId: 'first' })
        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'second' })
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
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'A1' })
        }).toDispatchActions(['loadTraceSpansSuccess'])

        logic.actions.toggleSpanCollapsed('A')

        expect(logic.values.selectedSpanId).toBe('A')
        expect(logic.values.flatSpans.map((node) => node.span.span_id)).toEqual(['ROOT', 'A'])
    })

    it('clears the failure once a retry succeeds', async () => {
        getTraceSpy.mockRejectedValueOnce(new Error('boom'))
        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'abc123' })
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
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'a' })
        })
            .toDispatchActions(['loadTraceSpansSuccess'])
            .toMatchValues({ activeInspectorTab: expectedTab })
    })

    it('keeps a picked tab across spans, and drops it for the next trace', async () => {
        getTraceSpy.mockResolvedValue({ results: [span('a', 2), span('b')], hasMore: false, nextOffset: null })
        logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'a' })
        await expectLogic(logic).toDispatchActions(['loadTraceSpansSuccess'])

        logic.actions.setInspectorTab('attributes')
        await expectLogic(logic, () => {
            logic.actions.selectSpan('b')
        }).toMatchValues({ activeInspectorTab: 'attributes' })

        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'def456', spanId: 'a' })
        })
            .toDispatchActions(['loadTraceSpansSuccess'])
            .toMatchValues({ activeInspectorTab: 'errors' })
    })
})
