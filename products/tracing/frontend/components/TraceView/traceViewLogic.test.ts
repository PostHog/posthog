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
            logic.actions.enableSpanKeys('[data-attr="trace-view-test"]')
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
        const children = Array.from({ length: 11 }, (_, i) => child(`c${i}`, 'root', 'SELECT orders', 10 + i))
        logic.actions.setSpans([root, ...children, child('cache', 'root', 'cache GET', 30)])
        logic.actions.selectSpan('c0')
        const rowIds = (): (string | undefined)[] => logic.values.spanRows.map((row) => rowSpanNode(row)?.span.span_id)
        expect(rowIds()).not.toContain('cache')

        logic.actions.highlightOperation(CACHE_GET)

        expect(rowIds()).toContain('cache')
        expect(logic.values.selectedSpanId).toBe('c0')
    })
})
