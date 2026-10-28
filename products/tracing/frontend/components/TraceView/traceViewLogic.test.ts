import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { makeSpan } from '../../__mocks__/span'
import { compareRowKey } from '../../compareUtils'
import type { Span } from '../../types'
import { rowSpanNode } from '../TraceDialog/traceDialogRows'
import { traceViewLogic } from './traceViewLogic'

const child = (span_id: string, parent_span_id: string, name: string, offsetMs: number): Span =>
    makeSpan({
        uuid: span_id,
        span_id,
        parent_span_id,
        name,
        is_root_span: false,
        timestamp: new Date(Date.UTC(2026, 8, 3, 10) + offsetMs).toISOString(),
    })

const root = makeSpan({ uuid: 'root', span_id: 'root', name: 'POST /api/orders' })
const CACHE_GET = compareRowKey({ service_name: 'checkout-api', name: 'cache GET' })

describe('traceViewLogic', () => {
    let logic: ReturnType<typeof traceViewLogic.build>
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_TRACE_FOLDED_RUNS]: true })
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        logic = traceViewLogic({ id: 'trace-view-test' })
        logic.mount()
        logic.actions.showTrace(null, 'operations')
    })

    afterEach(() => {
        logic.unmount()
        captureSpy.mockRestore()
    })

    // A stale key dims the next trace's tree. Another inspector tab, or the missing-parent notice that
    // replaces the inspector, would leave dimmed rows with nothing on screen to explain them. A switch to
    // the Operations tab itself must keep the pick, or a caller that selects the tab after a highlight drops it.
    // The Operations tab stays on screen in the call tree, which opens on the same operation, so a switch of
    // view must keep the pick too.
    // The tab event must count only the person's own switches: a trace that opens on a tab, or a click on the
    // tab already shown, would inflate it.
    it.each([
        { action: 'opening a trace', act: () => logic.actions.showTrace(null, null), keeps: false, tabEvent: null },
        {
            action: 'selecting the Logs tab',
            act: () => logic.actions.setInspectorTab('logs', 'drawer'),
            keeps: false,
            tabEvent: { tab: 'logs', surface: 'drawer' },
        },
        {
            action: 'another logic setting the Logs tab',
            act: () => logic.actions.setInspectorTab('logs'),
            keeps: false,
            tabEvent: null,
        },
        {
            action: 'selecting the missing parent',
            act: () => logic.actions.selectSpan('gone'),
            keeps: false,
            tabEvent: null,
        },
        {
            action: 'selecting the Operations tab',
            act: () => logic.actions.setInspectorTab('operations', 'trace_dialog'),
            keeps: true,
            tabEvent: null,
        },
        {
            action: 'switching to the call tree',
            act: () => {
                featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_TRACE_CALL_TREE]: true })
                logic.actions.setTraceViewMode('calltree', 'drawer')
            },
            keeps: true,
            tabEvent: null,
        },
    ])(
        'after $action, keeps the highlighted operation: $keeps, and sends a tab event only for a tab change',
        ({ act, keeps, tabEvent }) => {
            logic.actions.setSpans([root, child('orphan', 'gone', 'cache GET', 1)])
            logic.actions.highlightOperation(CACHE_GET)

            act()

            expect(logic.values.highlightedOperationKey).toBe(keeps ? CACHE_GET : null)
            expect(captureSpy.mock.calls.filter(([event]) => event === 'tracing trace inspector tab changed')).toEqual(
                tabEvent ? [['tracing trace inspector tab changed', tabEvent]] : []
            )
        }
    )

    // The call tree hides the span tree, so J there would move a selection that nobody can see. Back in the span
    // tree the keys must work again, and with the flag off a stored call tree must not turn them off. In every
    // view the key must stop at the view, or the page under it acts on the key too.
    it.each([
        { view: 'calltree' as const, flagOn: true, selected: 'a' },
        { view: 'waterfall' as const, flagOn: true, selected: 'b' },
        { view: 'calltree' as const, flagOn: false, selected: 'b' },
    ])(
        'in the $view view with the flag on: $flagOn, J leaves the selection on $selected',
        ({ view, flagOn, selected }) => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_TRACE_CALL_TREE]: flagOn })
            logic.actions.setSpans([root, child('a', 'root', 'SELECT orders', 1), child('b', 'root', 'cache GET', 2)])
            logic.actions.selectSpan('a')
            logic.actions.enableSpanKeys('[data-attr="trace-view-test"]', 'drawer')
            logic.actions.setTraceViewMode('calltree', 'drawer')
            logic.actions.setTraceViewMode(view, 'drawer')
            const pageKeyDown = jest.fn()
            document.body.addEventListener('keydown', pageKeyDown)

            const event = new KeyboardEvent('keydown', { key: 'j', bubbles: true, cancelable: true })
            document.body.dispatchEvent(event)
            document.body.removeEventListener('keydown', pageKeyDown)

            expect(logic.values.selectedSpanId).toBe(selected)
            expect([event.defaultPrevented, pageKeyDown.mock.calls.length]).toEqual([true, 0])
        }
    )

    // AI events load after the spans. A call tree rebuilt for them resets the drill-down in the flame.
    it('keeps the call tree when only AI event rows arrive', () => {
        const spans = [root, child('cache', 'root', 'cache GET', 1)]
        logic.actions.setSpans(spans)
        const callTree = logic.values.callTree

        logic.actions.setSpans([...spans, child('ai:event-1', 'root', 'llm call', 2)])

        expect(logic.values.callTree).toBe(callTree)
    })

    // Fails when the highlight stops opening the child list that hides the operation's first span, which
    // leaves the tree nothing to scroll to, or when it moves the selection off the span the person inspects.
    it('opens the child list that hides the first span of the highlighted operation, and keeps the selection', () => {
        // One operation each, so that no run folds them and they fill the cap.
        const children = Array.from({ length: 11 }, (_, i) => child(`c${i}`, 'root', `SELECT orders ${i}`, 10 + i))
        logic.actions.setSpans([root, ...children, child('cache', 'root', 'cache GET', 30)])
        logic.actions.selectSpan('c0')
        const rowIds = (): (string | undefined)[] => logic.values.spanRows.map((row) => rowSpanNode(row)?.span.span_id)
        expect(rowIds()).not.toContain('cache')

        logic.actions.highlightOperation(CACHE_GET)

        expect(rowIds()).toContain('cache')
        expect(logic.values.selectedSpanId).toBe('c0')
    })

    describe('runs', () => {
        // Three reads of one operation under the root, so they fold into one run.
        const reads = (...extra: Span[]): Span[] => [
            root,
            ...[1, 2, 3].map((i) => child(`get${i}`, 'root', 'cache GET', i)),
            ...extra,
        ]
        const rows = (): string[] =>
            logic.values.spanRows.map((row) =>
                row.kind === 'run' ? `${row.nodes.length} folded` : (rowSpanNode(row)?.span.span_id ?? '')
            )
        const toggleEvents = (): unknown[] =>
            captureSpy.mock.calls
                .filter(([event]) => event === 'tracing trace run toggled')
                .map(([, properties]) => properties)

        // Fails when the right arrow skips a folded run whose first span is a leaf, which leaves no key to open it,
        // or when the left arrow on any span of the opened run leaves the run open: a person deep in a long run must
        // not have to scroll back to its first span to fold it. Left treats every span of the run alike, so a span
        // with open children collapses them first. The toggle event must name the action, method and surface of
        // each toggle, so the funnel can tell an open from a fold.
        it.each([
            { member: 'its first span', extra: [], leftOn: 'get1', collapsesFirst: false },
            { member: 'a later span', extra: [], leftOn: 'get2', collapsesFirst: false },
            {
                member: 'its first span, which has open children',
                extra: [child('get1-call', 'get1', 'redis GET', 1)],
                leftOn: 'get1',
                collapsesFirst: true,
            },
        ])(
            'opens a folded run with the right arrow, and folds it with the left arrow on $member',
            ({ extra, leftOn, collapsesFirst }) => {
                logic.actions.setSpans(reads(...extra))
                logic.actions.selectSpan('root')

                logic.actions.selectNextSpan()
                expect([logic.values.selectedSpanId, rows()]).toEqual(['get1', ['root', '3 folded']])

                logic.actions.expandSelectedSpan('drawer')
                const opened = ['root', 'get1', 'get2', 'get3']
                expect(rows()).toEqual(collapsesFirst ? ['root', 'get1', 'get1-call', 'get2', 'get3'] : opened)

                logic.actions.selectSpan(leftOn)
                if (collapsesFirst) {
                    logic.actions.collapseSelectedSpan('drawer')
                    expect([logic.values.collapsedSpanIds, rows()]).toEqual([new Set([leftOn]), opened])
                }
                logic.actions.collapseSelectedSpan('drawer')
                expect([logic.values.selectedSpanId, rows()]).toEqual(['get1', ['root', '3 folded']])
                expect(toggleEvents()).toEqual([
                    { action: 'open', span_count: 3, method: 'key', surface: 'drawer' },
                    { action: 'fold', span_count: 3, method: 'key', surface: 'drawer' },
                ])
            }
        )

        // Fails when the left arrow on a folded run collapses the span it stands for instead of moving to the
        // parent. The run's first span has a child, so a collapse would change the tree.
        it('moves from a folded run to its parent with the left arrow, and collapses nothing', () => {
            logic.actions.setSpans(reads(child('get1-call', 'get1', 'redis GET', 1)))
            logic.actions.selectSpan('get1')

            logic.actions.collapseSelectedSpan('drawer')

            expect([logic.values.selectedSpanId, logic.values.collapsedSpanIds, rows()]).toEqual([
                'root',
                new Set(),
                ['root', '3 folded'],
            ])
        })

        // Fails when a fold that hides the selected span moves the selection up to the parent, which takes the
        // person out of the run they folded, or when a click toggle sends the wrong action or method.
        it.each([
            { selection: 'a span of the run', selectedSpanId: 'get2' },
            { selection: 'a span under a span of the run', selectedSpanId: 'get2-call' },
        ])('keeps the selection on the run when a fold hides $selection', ({ selectedSpanId }) => {
            logic.actions.setSpans(reads(child('get2-call', 'get2', 'redis GET', 2)))
            logic.actions.toggleRun('get1', 'click', 'trace_dialog')
            logic.actions.selectSpan(selectedSpanId)

            logic.actions.toggleRun('get1', 'click', 'trace_dialog')

            expect([logic.values.selectedSpanId, rows()]).toEqual(['get1', ['root', '3 folded']])
            expect(toggleEvents()).toEqual([
                { action: 'open', span_count: 3, method: 'click', surface: 'trace_dialog' },
                { action: 'fold', span_count: 3, method: 'click', surface: 'trace_dialog' },
            ])
        })

        // Fails when a later page folds the selected span into a run with the spans it adds, which hides the
        // selection, so J and K jump to the root. The reveal is not the person's own toggle, so it sends no event.
        it('opens the run that a later page folds the selected span into', () => {
            const [, get1, get2] = reads()
            logic.actions.setSpans([root, get1, get2])
            logic.actions.selectSpan('get2')

            logic.actions.setSpans(reads())
            expect(rows()).toEqual(['root', 'get1', 'get2', 'get3'])
            logic.actions.selectNextSpan()

            expect(logic.values.selectedSpanId).toBe('get3')
            expect(toggleEvents()).toEqual([])
        })
    })
})
