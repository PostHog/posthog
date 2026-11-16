import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { makeSpan } from '../../__mocks__/span'
import { compareRowKey } from '../../compareUtils'
import { TraceOperationsTab } from './TraceOperationsTab'

// Give the table real dimensions so react-window renders its rows. AutoSizer measures 0x0 in jsdom.
jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 600, width: 800 }),
}))

const child = (span_id: string, parent_span_id: string, name: string): ReturnType<typeof makeSpan> =>
    makeSpan({ uuid: span_id, span_id, parent_span_id, name, service_name: 'web', is_root_span: false })

const root = makeSpan({ uuid: 'root', span_id: 'root', name: 'GET /x', service_name: 'web' })
const select = child('select', 'root', 'SELECT')
const SPANS = [
    root,
    child('cache-1', 'root', 'cache GET'),
    child('cache-2', 'root', 'cache GET'),
    select,
    child('fetch', 'select', 'fetch rows'),
    child('cache-3', 'fetch', 'cache GET'),
]

describe('TraceOperationsTab', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => cleanup())

    // Fails when the toggle does not change the span list the table summarizes, or when "This span"
    // collects the wrong spans: the trace root counts 3 cache reads, and the direct children of SELECT
    // miss the one a level further down. Also fails when the tab shows the full column set, which pushes
    // Share out of the narrow inspector, or when a highlight reports a scope other than the one the counts are in.
    it.each([
        { scope: 'Whole trace', click: null, cacheGetCount: '3', header: '4 operations · 6 spans', value: 'trace' },
        {
            scope: 'This span',
            click: 'This span',
            cacheGetCount: '1',
            header: '3 operations · 3 spans under SELECT',
            value: 'span',
        },
    ])('counts the operations of the $scope scope and highlights in it', ({ click, cacheGetCount, header, value }) => {
        const onHighlightOperation = jest.fn()
        render(
            <TraceOperationsTab
                span={select}
                spans={SPANS}
                highlightedOperationKey={null}
                onHighlightOperation={onHighlightOperation}
                partial={false}
            />
        )
        if (click) {
            fireEvent.click(screen.getByText(click))
        }

        expect(screen.getByText(header)).toBeTruthy()
        expect(screen.queryByText('Avg')).toBeNull()
        const cacheGetRow = screen.getByText('cache GET').closest('[data-row-key]') as HTMLElement
        expect(within(cacheGetRow).getByText(cacheGetCount)).toBeTruthy()

        fireEvent.click(screen.getByText('cache GET'))
        expect(onHighlightOperation.mock.calls).toEqual([
            [compareRowKey({ service_name: 'web', name: 'cache GET' }), value],
        ])
    })
})
