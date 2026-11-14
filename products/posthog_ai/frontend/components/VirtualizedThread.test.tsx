import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { FLOW_INITIAL_ROWS } from '../utils/flowWindow'
import { VirtualizedThread } from './VirtualizedThread'

const mockUseVirtualizer = jest.fn()

jest.mock('@tanstack/react-virtual', () => ({
    elementScroll: jest.fn(),
    useVirtualizer: (options: unknown) => mockUseVirtualizer(options),
}))

interface MockVirtualItem {
    index: number
    key: string
    start: number
    size: number
    end: number
    lane: number
}

function createLazyMeasurements(count: number, getItemKey: (index: number) => string): MockVirtualItem[] {
    const cache = new Array<MockVirtualItem | undefined>(count)
    return new Proxy(cache, {
        get(target, property, receiver) {
            if (typeof property === 'string' && /^\d+$/.test(property)) {
                const index = Number(property)
                if (index < count) {
                    return (target[index] ??= {
                        index,
                        key: getItemKey(index),
                        start: index * 56,
                        size: 56,
                        end: (index + 1) * 56,
                        lane: 0,
                    })
                }
            }
            return Reflect.get(target, property, receiver)
        },
    }) as MockVirtualItem[]
}

function createMockVirtualizer(options: { count: number; getItemKey: (index: number) => string }): object {
    const measurementsCache = createLazyMeasurements(options.count, options.getItemKey)
    return {
        containerRef: jest.fn(),
        getOffsetForIndex: jest.fn(() => [0]),
        getTotalSize: jest.fn(() => options.count * 56),
        getVirtualItems: jest.fn(() => [measurementsCache[0]]),
        measureElement: jest.fn(),
        measurementsCache,
        options: { anchorTo: 'end', scrollEndThreshold: 32 },
        scrollToIndex: jest.fn(),
    }
}

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

describe('VirtualizedThread', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        mockUseVirtualizer.mockImplementation(createMockVirtualizer)
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

    it('opens when the header is the first visible row in a lazy measurement cache', () => {
        expect(() =>
            render(
                <VirtualizedThread.Root items={['row-0']} getItemKey={(item) => item} header={<div>header</div>}>
                    {(item) => (
                        <VirtualizedThread.Row>
                            <p>{item}</p>
                        </VirtualizedThread.Row>
                    )}
                </VirtualizedThread.Root>
            )
        ).not.toThrow()
    })
})
