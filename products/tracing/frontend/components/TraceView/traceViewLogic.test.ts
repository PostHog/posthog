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

    beforeEach(() => {
        initKeaTests()
        logic = traceViewLogic({ id: 'trace-view-test' })
        logic.mount()
        logic.actions.showTrace(null, 'operations')
    })

    afterEach(() => {
        logic.unmount()
    })

    // A stale key dims the next trace's tree. Another inspector tab, or the missing-parent notice that
    // replaces the inspector, would leave dimmed rows with nothing on screen to explain them. A switch to
    // the Operations tab itself must keep the pick, or a caller that selects the tab after a highlight drops it.
    it.each([
        { action: 'opening a trace', act: () => logic.actions.showTrace(null, null), keeps: false },
        { action: 'selecting the Logs tab', act: () => logic.actions.setInspectorTab('logs'), keeps: false },
        { action: 'selecting the missing parent', act: () => logic.actions.selectSpan('gone'), keeps: false },
        {
            action: 'selecting the Operations tab',
            act: () => logic.actions.setInspectorTab('operations'),
            keeps: true,
        },
    ])('after $action, keeps the highlighted operation: $keeps', ({ act, keeps }) => {
        logic.actions.setSpans([root, child('orphan', 'gone', 'cache GET', 1)])
        logic.actions.highlightOperation(CACHE_GET)

        act()

        expect(logic.values.highlightedOperationKey).toBe(keeps ? CACHE_GET : null)
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
