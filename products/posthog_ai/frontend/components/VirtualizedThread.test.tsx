import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { FLOW_INITIAL_ROWS } from '../utils/flowWindow'
import { VirtualizedThread } from './VirtualizedThread'

function thread(items: string[]): JSX.Element {
    return (
        <div data-attr="thread">
            <VirtualizedThread.Root items={items} getItemKey={(item) => item} virtualized={false}>
                {(item) => (
                    <VirtualizedThread.Row>
                        <p>{item}</p>
                    </VirtualizedThread.Row>
                )}
            </VirtualizedThread.Root>
        </div>
    )
}

function rows(from: number, to: number): string[] {
    return Array.from({ length: to - from }, (_, index) => `row-${from + index}`)
}

function renderedRows(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll('p')).map((row) => row.textContent ?? '')
}

describe('VirtualizedThread flow mode', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('shows the newest rows first, keeps bulk appends small, then fills in the full history in order', () => {
        const history = rows(0, 300)
        const { container, rerender } = render(thread(history))

        const firstPaint = renderedRows(container)
        expect(firstPaint.at(-1)).toBe('row-299')
        expect(firstPaint).not.toContain('row-0')

        const streamed = [...history, 'row-300']
        rerender(thread(streamed))
        expect(renderedRows(container).at(-1)).toBe('row-300')

        act(() => {
            jest.runOnlyPendingTimers()
        })
        const beforeAppend = renderedRows(container)

        // A history replay that lands in several commits appends hundreds of rows to a thread mid-fill.
        const appended = [...streamed, ...rows(301, 700)]
        rerender(thread(appended))
        const afterAppend = renderedRows(container)
        expect(afterAppend.at(-1)).toBe('row-699')
        expect(afterAppend.length - beforeAppend.length).toBeLessThanOrEqual(FLOW_INITIAL_ROWS)
        expect(afterAppend).toEqual(expect.arrayContaining(beforeAppend))

        for (let step = 0; step < 100 && renderedRows(container).length < appended.length; step++) {
            act(() => {
                jest.runOnlyPendingTimers()
            })
        }
        expect(renderedRows(container)).toEqual(appended)
    })
})
