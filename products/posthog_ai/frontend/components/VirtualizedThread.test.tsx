import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'

import { VirtualizedThread } from './VirtualizedThread'

function renderThread(items: string[]): ReturnType<typeof render> {
    return render(
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

function renderedRows(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll('p')).map((row) => row.textContent ?? '')
}

describe('VirtualizedThread flow mode', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('shows the newest rows first, then fills in the full history in order without delaying new rows', () => {
        const history = Array.from({ length: 300 }, (_, index) => `row-${index}`)
        const { container, rerender } = renderThread(history)

        const firstPaint = renderedRows(container)
        expect(firstPaint.at(-1)).toBe('row-299')
        expect(firstPaint).not.toContain('row-0')

        const streamed = [...history, 'row-300']
        rerender(
            <div data-attr="thread">
                <VirtualizedThread.Root items={streamed} getItemKey={(item) => item} virtualized={false}>
                    {(item) => (
                        <VirtualizedThread.Row>
                            <p>{item}</p>
                        </VirtualizedThread.Row>
                    )}
                </VirtualizedThread.Root>
            </div>
        )
        expect(renderedRows(container).at(-1)).toBe('row-300')

        for (let step = 0; step < 100 && renderedRows(container).length < streamed.length; step++) {
            act(() => {
                jest.runOnlyPendingTimers()
            })
        }
        expect(renderedRows(container)).toEqual(streamed)
    })
})
