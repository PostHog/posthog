import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { JSX, MutableRefObject, ReactNode } from 'react'

import { VirtualizedList, VirtualizedListHandle } from './VirtualizedList'

interface TestItem {
    id: string
    label: string
}

const VIEWPORT_HEIGHT = 400
const DEFAULT_ROW_HEIGHT = 100
const AT_BOTTOM_THRESHOLD = 50

let rowHeightValue = DEFAULT_ROW_HEIGHT
let footerHeightValue = 40

const scrollTopState = new WeakMap<Element, number>()

class MockResizeObserver {
    static instances: MockResizeObserver[] = []
    readonly targets: Element[] = []

    constructor(private readonly callback: ResizeObserverCallback) {
        MockResizeObserver.instances.push(this)
    }

    observe(target: Element): void {
        this.targets.push(target)
    }

    unobserve(target: Element): void {
        const index = this.targets.indexOf(target)
        if (index >= 0) {
            this.targets.splice(index, 1)
        }
    }

    disconnect(): void {
        this.targets.length = 0
    }

    trigger(): void {
        this.callback([], this as unknown as ResizeObserver)
    }
}

const overriddenProperties: { key: string; descriptor: PropertyDescriptor | undefined }[] = []

function overrideProperty(key: string, descriptor: PropertyDescriptor): void {
    overriddenProperties.push({ key, descriptor: Object.getOwnPropertyDescriptor(HTMLElement.prototype, key) })
    Object.defineProperty(HTMLElement.prototype, key, { configurable: true, ...descriptor })
}

function isScrollContainer(el: HTMLElement): boolean {
    return el.getAttribute('data-attr') === 'virtualized-list-scroll'
}

let frameCallbacks = new Map<number, FrameRequestCallback>()
let nextFrameId = 0

function flushFrames(maxFrames = 30): void {
    for (let frame = 0; frame < maxFrames && frameCallbacks.size > 0; frame++) {
        const callbacks = Array.from(frameCallbacks.values())
        frameCallbacks.clear()
        act(() => {
            for (const callback of callbacks) {
                callback(frame)
            }
        })
    }
}

function getScrollContainer(): HTMLElement {
    const el = document.querySelector<HTMLElement>('[data-attr="virtualized-list-scroll"]')
    if (!el) {
        throw new Error('Scroll container not found')
    }
    return el
}

function getSpacerHeight(): number {
    const spacer = getScrollContainer().firstElementChild as HTMLElement | null
    return spacer ? parseFloat(spacer.style.height || '0') : 0
}

function distanceFromEnd(): number {
    const container = getScrollContainer()
    return container.scrollHeight - container.clientHeight - container.scrollTop
}

function userScrollTo(scrollTop: number): void {
    fireEvent.scroll(getScrollContainer(), { target: { scrollTop } })
}

function makeItems(count: number): TestItem[] {
    return Array.from({ length: count }, (_, i) => ({ id: `item-${i}`, label: `Item ${i}` }))
}

interface RenderListOptions {
    count?: number
    footer?: ReactNode
    keepMounted?: readonly number[]
}

interface RenderedList {
    onScrollStateChange: jest.Mock
    listRef: MutableRefObject<VirtualizedListHandle | null>
    rerenderItems: (items: TestItem[]) => void
}

function renderList(options: RenderListOptions = {}): RenderedList {
    const onScrollStateChange = jest.fn()
    const listRef: MutableRefObject<VirtualizedListHandle | null> = { current: null }
    const buildElement = (items: TestItem[]): JSX.Element => (
        <VirtualizedList<TestItem>
            ref={listRef}
            items={items}
            getItemKey={(item) => item.id}
            renderItem={(item) => <div>{item.label}</div>}
            onScrollStateChange={onScrollStateChange}
            footer={options.footer}
            keepMounted={options.keepMounted}
        />
    )
    const view = render(buildElement(makeItems(options.count ?? 30)))
    flushFrames()
    return {
        onScrollStateChange,
        listRef,
        rerenderItems: (items: TestItem[]): void => {
            view.rerender(buildElement(items))
            flushFrames()
        },
    }
}

describe('VirtualizedList', () => {
    beforeAll(() => {
        overrideProperty('offsetHeight', {
            get(this: HTMLElement): number {
                if (isScrollContainer(this)) {
                    return VIEWPORT_HEIGHT
                }
                if (this.getAttribute('data-attr') === 'virtualized-list-footer') {
                    return footerHeightValue
                }
                if (this.hasAttribute('data-index')) {
                    return rowHeightValue
                }
                return 0
            },
        })
        overrideProperty('offsetWidth', {
            get(): number {
                return 600
            },
        })
        overrideProperty('clientHeight', {
            get(this: HTMLElement): number {
                return isScrollContainer(this) ? VIEWPORT_HEIGHT : 0
            },
        })
        overrideProperty('scrollHeight', {
            get(this: HTMLElement): number {
                if (!isScrollContainer(this)) {
                    return 0
                }
                const spacer = this.firstElementChild as HTMLElement | null
                return spacer ? parseFloat(spacer.style.height || '0') : 0
            },
        })
        overrideProperty('scrollTop', {
            get(this: HTMLElement): number {
                return scrollTopState.get(this) ?? 0
            },
            set(this: HTMLElement, value: number): void {
                scrollTopState.set(this, value)
            },
        })
        overrideProperty('scrollTo', {
            value(this: HTMLElement, options?: ScrollToOptions | number, y?: number): void {
                const top = typeof options === 'object' ? (options?.top ?? this.scrollTop) : (y ?? 0)
                this.scrollTop = top
                this.dispatchEvent(new Event('scroll'))
            },
        })
    })

    afterAll(() => {
        for (const { key, descriptor } of overriddenProperties) {
            if (descriptor) {
                Object.defineProperty(HTMLElement.prototype, key, descriptor)
            } else {
                delete (HTMLElement.prototype as unknown as Record<string, unknown>)[key]
            }
        }
    })

    beforeEach(() => {
        jest.useFakeTimers()
        frameCallbacks = new Map()
        nextFrameId = 0
        window.requestAnimationFrame = (callback: FrameRequestCallback): number => {
            frameCallbacks.set(++nextFrameId, callback)
            return nextFrameId
        }
        window.cancelAnimationFrame = (id: number): void => {
            frameCallbacks.delete(id)
        }
        MockResizeObserver.instances = []
        ;(globalThis as unknown as Record<string, unknown>).ResizeObserver = MockResizeObserver
        rowHeightValue = DEFAULT_ROW_HEIGHT
        footerHeightValue = 40
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('pins to the bottom on initial render without reporting unpinned transients', () => {
        const { onScrollStateChange } = renderList({ count: 30 })

        expect(getScrollContainer().scrollTop).toBeGreaterThan(0)
        expect(distanceFromEnd()).toBeLessThanOrEqual(AT_BOTTOM_THRESHOLD)
        expect(onScrollStateChange.mock.calls.some(([isAtBottom]) => isAtBottom === false)).toBe(false)
    })

    it('measures row heights and grows the virtual space beyond the estimate', () => {
        renderList({ count: 5 })

        // 5 rows measured at 100px each, vs the 80px estimate (= 400px).
        expect(getSpacerHeight()).toBe(5 * DEFAULT_ROW_HEIGHT)
    })

    it('unpins on a real upward scroll and re-pins when scrolled back to the bottom', () => {
        const { onScrollStateChange } = renderList({ count: 30 })
        onScrollStateChange.mockClear()

        userScrollTo(getScrollContainer().scrollTop - 200)
        expect(onScrollStateChange).toHaveBeenLastCalledWith(false)

        flushFrames()
        userScrollTo(getSpacerHeight() - VIEWPORT_HEIGHT)
        expect(onScrollStateChange).toHaveBeenLastCalledWith(true)
    })

    it('stays pinned through a small upward dip within the bottom threshold', () => {
        const { onScrollStateChange } = renderList({ count: 30 })
        onScrollStateChange.mockClear()

        userScrollTo(getScrollContainer().scrollTop - 30)
        expect(onScrollStateChange).toHaveBeenLastCalledWith(true)
    })

    it('keeps reporting unpinned while far from the end, even on downward scrolls', () => {
        const { onScrollStateChange } = renderList({ count: 30 })
        onScrollStateChange.mockClear()

        userScrollTo(getScrollContainer().scrollTop - 600)
        expect(onScrollStateChange).toHaveBeenLastCalledWith(false)
        flushFrames()

        // Downward scroll that still leaves the bottom > 400px away: no re-pin.
        userScrollTo(getSpacerHeight() - VIEWPORT_HEIGHT - 450)
        expect(onScrollStateChange).toHaveBeenLastCalledWith(false)
        flushFrames()

        userScrollTo(getSpacerHeight() - VIEWPORT_HEIGHT - 10)
        expect(onScrollStateChange).toHaveBeenLastCalledWith(true)
    })

    it('scrollToIndex overrides scrollToBottom and stays put through later remeasures', () => {
        const { listRef, onScrollStateChange } = renderList({ count: 50 })
        expect(listRef.current).toBeTruthy()

        act(() => {
            listRef.current?.scrollToBottom()
            listRef.current?.scrollToIndex(2)
        })
        flushFrames()

        // Near item 2, far from the end, and totalSize changes must not re-pin.
        expect(getScrollContainer().scrollTop).toBeLessThan(500)
        expect(distanceFromEnd()).toBeGreaterThan(400)
        expect(onScrollStateChange).toHaveBeenLastCalledWith(false)
    })

    it('re-pins to the new bottom when the footer grows while pinned', () => {
        renderList({ count: 10, footer: <div>Footer content</div> })

        expect(document.body.textContent).toContain('Footer content')
        expect(getSpacerHeight()).toBe(10 * DEFAULT_ROW_HEIGHT + footerHeightValue)
        expect(distanceFromEnd()).toBeLessThanOrEqual(AT_BOTTOM_THRESHOLD)

        footerHeightValue = 140
        const footerObserver = MockResizeObserver.instances.find((instance) =>
            instance.targets.some((target) => target.getAttribute('data-attr') === 'virtualized-list-footer')
        )
        expect(footerObserver).toBeTruthy()
        act(() => footerObserver?.trigger())
        flushFrames()

        expect(getSpacerHeight()).toBe(10 * DEFAULT_ROW_HEIGHT + 140)
        expect(distanceFromEnd()).toBeLessThanOrEqual(AT_BOTTOM_THRESHOLD)
    })

    it('keeps keep-mounted rows in the DOM, hidden and inert, when virtualized out', () => {
        renderList({ count: 60, keepMounted: [0] })

        const keptItem = document.querySelector<HTMLElement>('[data-conversation-item-id="item-0"]')
        expect(keptItem).toBeTruthy()
        const wrapper = keptItem?.parentElement as HTMLElement
        expect(wrapper.getAttribute('aria-hidden')).toBe('true')
        expect(wrapper.className).toContain('invisible')
        expect(wrapper.className).toContain('pointer-events-none')
        expect(wrapper.style.transform).toBe('translateY(-99999px)')

        // A non-kept off-screen row is not in the DOM; the last row renders normally.
        expect(document.querySelector('[data-conversation-item-id="item-30"]')).toBeNull()
        const lastItem = document.querySelector<HTMLElement>('[data-conversation-item-id="item-59"]')
        expect(lastItem).toBeTruthy()
        expect(lastItem?.parentElement?.getAttribute('aria-hidden')).toBeNull()
    })

    it('re-pins on visibilitychange only while still pinned', () => {
        renderList({ count: 30 })
        const container = getScrollContainer()

        // Drift without scroll events (e.g. browser-restored position): still pinned.
        container.scrollTop = container.scrollTop - 300
        act(() => {
            document.dispatchEvent(new Event('visibilitychange'))
        })
        flushFrames()
        expect(distanceFromEnd()).toBeLessThanOrEqual(AT_BOTTOM_THRESHOLD)

        // After a genuine user scroll up, visibilitychange must not yank back down.
        userScrollTo(container.scrollTop - 600)
        flushFrames()
        const unpinnedScrollTop = container.scrollTop
        act(() => {
            document.dispatchEvent(new Event('visibilitychange'))
        })
        flushFrames()
        expect(container.scrollTop).toBe(unpinnedScrollTop)
    })

    it('stays pinned across streaming appends without unpinned transients', () => {
        const { onScrollStateChange, rerenderItems } = renderList({ count: 20 })

        for (const count of [22, 25, 28, 30]) {
            rerenderItems(makeItems(count))
            expect(distanceFromEnd()).toBeLessThanOrEqual(AT_BOTTOM_THRESHOLD)
        }
        expect(onScrollStateChange.mock.calls.every(([isAtBottom]) => isAtBottom === true)).toBe(true)
    })
})
