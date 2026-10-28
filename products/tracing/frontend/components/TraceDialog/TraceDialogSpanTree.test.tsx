import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { compareRowKey } from 'products/tracing/frontend/compareUtils'
import type { Span } from 'products/tracing/frontend/types'

import { traceViewLogic } from '../TraceView/traceViewLogic'
import { TRACE_DIALOG_VIEW_ID, traceDialogLogic } from './traceDialogLogic'
import { TraceDialogSpanTree, type TraceDialogSpanTreeProps } from './TraceDialogSpanTree'

function span(spanId: string, parentSpanId: string): Span {
    return {
        uuid: spanId,
        trace_id: 'abc123',
        span_id: spanId,
        parent_span_id: parentSpanId,
        name: `${spanId} span`,
        kind: 0,
        service_name: 'agent-worker',
        status_code: 0,
        timestamp: '2026-10-14T10:00:00.000000Z',
        end_time: '2026-10-14T10:00:01.000000Z',
        duration_nano: 1_000_000_000,
        is_root_span: parentSpanId === '',
        matched_filter: true,
        attributes: {},
        resource_attributes: {},
    }
}

function renderTree(viewId: string, spans: Span[], props: Partial<TraceDialogSpanTreeProps> = {}): HTMLElement {
    const view = traceViewLogic({ id: viewId })
    view.mount()
    view.actions.showTrace(null, null)
    view.actions.setSpans(spans)
    view.actions.selectSpan(spans[0].span_id)
    return render(
        <Provider>
            <BindLogic logic={traceViewLogic} props={{ id: viewId }}>
                <TraceDialogSpanTree surface="drawer" openedFrom={null} openedAtUs={null} {...props} />
            </BindLogic>
        </Provider>
    ).container
}

describe('TraceDialogSpanTree', () => {
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_TRACE_FOLDED_RUNS]: true })
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        // jsdom lays nothing out, so the virtualized list needs a size to render rows into.
        jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(600)
        jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(1000)
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
        delete (Element.prototype as Partial<Element>).scrollTo
    })

    it('renders a loaded trace and steps the selection with J', async () => {
        jest.spyOn(api.tracing, 'getTrace').mockResolvedValue({
            results: [span('ROOT', ''), span('A', 'ROOT'), span('B', 'ROOT')],
            hasMore: false,
            nextOffset: null,
        })
        const logic = traceDialogLogic()
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'A' }, { entryPoint: 'log_details' })
        }).toDispatchActions(['loadTraceSpansSuccess'])

        const { container } = render(
            <Provider>
                <BindLogic logic={traceViewLogic} props={{ id: TRACE_DIALOG_VIEW_ID }}>
                    <TraceDialogSpanTree surface="trace_dialog" openedFrom={null} openedAtUs={null} />
                </BindLogic>
            </Provider>
        )
        logic.actions.selectNextSpan()

        await waitFor(() =>
            expect(container.querySelector('[data-attr="trace-dialog-span-row"][aria-pressed="true"]')).toHaveAttribute(
                'aria-label',
                'B span'
            )
        )
    })

    // Fails when the highlight dims by the wrong key, or dims a folded chain that hides a span of the
    // operation, which would tell the person the operation is not in there.
    it('dims the rows outside the highlighted operation', async () => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_TRACE_OPERATIONS_TAB]: true })
        const view = traceViewLogic({ id: 'span-tree-test' })
        view.mount()
        view.actions.showTrace(null, 'operations')
        // ROOT > A, B and B > C > D > E > F, where A and D are the operation and C to E fold into a chain.
        view.actions.setSpans([
            span('ROOT', ''),
            { ...span('A', 'ROOT'), name: 'cache GET' },
            span('B', 'ROOT'),
            span('C', 'B'),
            { ...span('D', 'C'), name: 'cache GET' },
            span('E', 'D'),
            span('F', 'E'),
        ])
        view.actions.highlightOperation(compareRowKey({ service_name: 'agent-worker', name: 'cache GET' }))

        render(
            <Provider>
                <BindLogic logic={traceViewLogic} props={{ id: 'span-tree-test' }}>
                    <TraceDialogSpanTree surface="trace_dialog" openedFrom={null} openedAtUs={null} />
                </BindLogic>
            </Provider>
        )

        await screen.findByText('cache GET')
        const isDimmed = (name: string): boolean => screen.getByText(name).classList.contains('opacity-40')
        expect(isDimmed('cache GET')).toBe(false)
        expect(isDimmed('C span › … › E span')).toBe(false)
        expect([isDimmed('ROOT span'), isDimmed('B span'), isDimmed('F span')]).toEqual([true, true, true])
    })

    // Fails when a page of spans that loads after the scroll to the operation pulls the list back to the selected
    // span, which leaves the highlighted spans off screen.
    it('keeps the highlighted operation in view when another page of spans loads', async () => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_TRACE_OPERATIONS_TAB]: true })
        const view = traceViewLogic({ id: 'span-tree-page-test' })
        view.mount()
        view.actions.showTrace(null, 'operations')
        // ROOT > P0 to P9 > five spans each: 61 rows, more than the list shows. The last row is the operation.
        const spans = [span('ROOT', ''), ...Array.from({ length: 10 }, (_, i) => span(`P${i}`, 'ROOT'))]
        for (let i = 0; i < 10; i++) {
            spans.push(...Array.from({ length: 5 }, (_, j) => span(`Q${i}-${j}`, `P${i}`)))
        }
        spans[spans.length - 1] = { ...spans[spans.length - 1], name: 'cache GET' }
        view.actions.setSpans(spans)
        // jsdom does not scroll, so a scroll sets the offset the list reads and fires the event it listens for.
        Element.prototype.scrollTo = function (this: Element, options?: ScrollToOptions | number) {
            this.scrollTop = typeof options === 'object' ? (options.top ?? 0) : 0
            this.dispatchEvent(new Event('scroll'))
        }
        const onLoadMore = jest.fn()
        const { container } = render(
            <Provider>
                <BindLogic logic={traceViewLogic} props={{ id: 'span-tree-page-test' }}>
                    <TraceDialogSpanTree
                        surface="drawer"
                        openedFrom={null}
                        openedAtUs={null}
                        hasMore
                        onLoadMore={onLoadMore}
                    />
                </BindLogic>
            </Provider>
        )
        await screen.findByText('ROOT span')

        act(() => view.actions.highlightOperation(compareRowKey({ service_name: 'agent-worker', name: 'cache GET' })))
        await screen.findByText('cache GET')
        // The tree pages only once the person moves it, so a wheel at the operation loads the next page.
        fireEvent.wheel(container.querySelector('[role="list"]')!)
        expect(onLoadMore).toHaveBeenCalled()
        act(() => view.actions.setSpans([...spans, span('LATE', 'P9')]))

        expect(screen.getByText('cache GET')).toBeInTheDocument()
    })

    // A loop of identical calls must take one row, and opening that row must not select a span, which would
    // move the inspector to a span the person did not pick. Fails too when a click toggle reaches the logic
    // without its method or surface, when an Enter on the focused fold control counts as a click, or when the
    // fold, which shows the run again, sends the runs shown event a second time.
    it('opens a folded run on click without selecting a span, and folds it again', async () => {
        const reads = ['A', 'B', 'C'].map((spanId) => ({ ...span(spanId, 'ROOT'), name: 'cache GET' }))
        const container = renderTree('span-tree-run-test', [span('ROOT', ''), ...reads])
        const selectedSpanId = (): string | null => traceViewLogic({ id: 'span-tree-run-test' }).values.selectedSpanId

        await waitFor(() => expect(container.querySelector('[data-attr="tracing-trace-expand-run"]')).not.toBeNull())
        expect(screen.getAllByText('cache GET')).toHaveLength(1)
        // A pointer click counts its presses in `detail`. A click that Enter fires on a focused button counts none.
        fireEvent.click(container.querySelector('[data-attr="tracing-trace-expand-run"]')!, { detail: 1 })

        await waitFor(() => expect(screen.getAllByText('cache GET')).toHaveLength(3))
        expect(selectedSpanId()).toBe('ROOT')

        fireEvent.click(container.querySelector('[data-attr="tracing-trace-fold-run"]')!, { detail: 0 })
        await waitFor(() => expect(screen.getAllByText('cache GET')).toHaveLength(1))
        expect(selectedSpanId()).toBe('ROOT')
        expect(captureSpy.mock.calls.filter(([event]) => event === 'tracing trace run toggled')).toEqual([
            ['tracing trace run toggled', { action: 'open', span_count: 3, method: 'click', surface: 'drawer' }],
            ['tracing trace run toggled', { action: 'fold', span_count: 3, method: 'key', surface: 'drawer' }],
        ])
        expect(captureSpy.mock.calls.filter(([event]) => event === 'tracing trace runs shown')).toEqual([
            ['tracing trace runs shown', { run_count: 1, largest_run: 3, surface: 'drawer' }],
        ])
    })

    // A folded run hides the spans under its own spans too. Fails when an error down there leaves no mark on the
    // run's row, or when it marks the row red like a failed call of the run itself.
    it.each([
        { where: 'one of its spans', errored: 'B', label: 'Error', isRed: true },
        { where: 'a span under it', errored: 'B1', label: 'Error in nested spans', isRed: false },
    ])('marks a folded run with an error in $where', async ({ errored, label, isRed }) => {
        const reads = ['A', 'B', 'C'].map((spanId) => ({ ...span(spanId, 'ROOT'), name: 'cache GET' }))
        const spans = [span('ROOT', ''), ...reads, span('B1', 'B')].map((loaded) =>
            loaded.span_id === errored ? { ...loaded, status_code: 2 } : loaded
        )
        renderTree('span-tree-run-error-test', spans)

        await screen.findByLabelText(label)
        expect(screen.getByText('cache GET').classList.contains('text-danger')).toBe(isRed)
    })

    // Fails when Show all has no way back, when Show fewer leaves the full list on screen, or when it leaves the
    // inspector on a selected child that the shorter list hides.
    it('shortens a full child list again with Show fewer, and moves a hidden selection to the parent', async () => {
        const children = Array.from({ length: 12 }, (_, i) => span(`C${i}`, 'ROOT'))
        const container = renderTree('span-tree-show-fewer-test', [span('ROOT', ''), ...children])
        // jsdom has no layout, so the list renders only the overscan rows around its scroll position, and each change
        // of the rows scrolls back to the selected root. A scroll down brings the end of the child list into range.
        const scrollDown = (): void => {
            fireEvent.scroll(container.querySelector('[role="list"]')!, { target: { scrollTop: 400 } })
        }

        scrollDown()
        fireEvent.click(await screen.findByText('Show all'))
        scrollDown()
        await screen.findByText('C11 span')
        expect(screen.queryByText('2 more spans')).toBeNull()
        const view = traceViewLogic({ id: 'span-tree-show-fewer-test' })
        act(() => view.actions.selectSpan('C11'))

        fireEvent.click(container.querySelector('[data-attr="trace-dialog-show-fewer-spans"]')!)
        scrollDown()
        await screen.findByText('2 more spans')
        expect(screen.queryByText('C11 span')).toBeNull()
        expect(view.values.selectedSpanId).toBe('ROOT')
    })

    // Fails when a trace that folds no run sends the event, when a later page of the same trace sends it again,
    // when only the first page counts, which misses a trace whose runs arrive with a later page, or when the next
    // trace sends nothing because its runs replace the last trace's without a render of the empty list.
    it.each([
        {
            trace: 'a run, then a page with another run',
            first: ['A', 'B', 'C'].map((spanId) => ({ ...span(spanId, 'ROOT'), name: 'cache GET' })),
            more: ['D', 'E', 'F', 'G'].map((spanId) => ({ ...span(spanId, 'ROOT'), name: 'redis GET' })),
            nextTrace: false,
            sent: [{ run_count: 1, largest_run: 3, surface: 'drawer' }],
        },
        {
            trace: 'no run',
            first: [span('A', 'ROOT')],
            more: [span('B', 'ROOT')],
            nextTrace: false,
            sent: [],
        },
        {
            trace: 'a run only on its second page',
            first: [span('A', 'ROOT')],
            more: ['B', 'C', 'D', 'E'].map((spanId) => ({ ...span(spanId, 'ROOT'), name: 'cache GET' })),
            nextTrace: false,
            sent: [{ run_count: 1, largest_run: 4, surface: 'drawer' }],
        },
        {
            trace: 'a run, then a second trace with runs',
            first: ['A', 'B', 'C'].map((spanId) => ({ ...span(spanId, 'ROOT'), name: 'cache GET' })),
            more: ['D', 'E', 'F', 'G'].map((spanId) => ({ ...span(spanId, 'ROOT'), name: 'redis GET' })),
            nextTrace: true,
            sent: [
                { run_count: 1, largest_run: 3, surface: 'drawer' },
                { run_count: 2, largest_run: 4, surface: 'drawer' },
            ],
        },
    ])('sends the runs shown event once per trace, given $trace', ({ first, more, nextTrace, sent }) => {
        const loaded = [span('ROOT', ''), ...first]
        renderTree('span-tree-runs-shown-test', loaded)
        const view = traceViewLogic({ id: 'span-tree-runs-shown-test' })
        act(() => {
            if (nextTrace) {
                view.actions.showTrace(null, null)
            }
            view.actions.setSpans([...loaded, ...more])
        })

        expect(
            captureSpy.mock.calls.filter(([event]) => event === 'tracing trace runs shown').map(([, props]) => props)
        ).toEqual(sent)
    })

    // Folded runs can make a large trace a few rows tall, so the end of the list is in view from the start.
    // Fails when the tree pages on that alone, which loads the whole trace without the person asking for it, or
    // when a J step to the end of the loaded spans no longer pages, because the view's key handler stops J
    // before the list sees it.
    it.each([
        { movement: 'a wheel scroll', move: (list: Element) => fireEvent.wheel(list) },
        {
            movement: 'a J step',
            move: () => traceViewLogic({ id: 'span-tree-paging-test' }).actions.selectNextSpan(),
        },
    ])('loads more spans only once the person moves the tree, here with $movement', async ({ move }) => {
        const onLoadMore = jest.fn()
        const container = renderTree('span-tree-paging-test', [span('ROOT', ''), span('A', 'ROOT')], {
            hasMore: true,
            onLoadMore,
        })

        await screen.findByText('A span')
        expect(onLoadMore).not.toHaveBeenCalled()

        move(container.querySelector('[role="list"]')!)
        await waitFor(() => expect(onLoadMore).toHaveBeenCalledTimes(1))
    })

    // Fails when the paging guard outlives its trace. The logic can hand over the next trace's spans in the same
    // tick as showTrace, so no render shows the empty list, and the page requested at the last trace's span count
    // would then block the next trace's first page.
    it('pages the next trace once the person moves it, when its spans arrive in the same tick as the trace', async () => {
        const onLoadMore = jest.fn()
        const container = renderTree('span-tree-paging-trace-test', [span('ROOT', ''), span('A', 'ROOT')], {
            hasMore: true,
            onLoadMore,
        })
        await screen.findByText('A span')
        fireEvent.wheel(container.querySelector('[role="list"]')!)
        await waitFor(() => expect(onLoadMore).toHaveBeenCalledTimes(1))

        const view = traceViewLogic({ id: 'span-tree-paging-trace-test' })
        act(() => {
            view.actions.showTrace(null, null)
            view.actions.setSpans([span('NEXT', ''), span('B', 'NEXT')])
        })
        await screen.findByText('B span')
        expect(onLoadMore).toHaveBeenCalledTimes(1)

        fireEvent.wheel(container.querySelector('[role="list"]')!)
        await waitFor(() => expect(onLoadMore).toHaveBeenCalledTimes(2))
    })
})
