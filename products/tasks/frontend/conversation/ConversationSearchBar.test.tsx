import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { JSX, MutableRefObject, useRef } from 'react'

import type { ConversationItem } from './buildConversationItems'
import { ConversationSearchBar } from './ConversationSearchBar'
import type { VirtualizedListHandle } from './VirtualizedList'

class MockHighlight {
    readonly ranges: Range[]
    constructor(...ranges: Range[]) {
        this.ranges = ranges
    }
}

class MockMutationObserver {
    static instances: MockMutationObserver[] = []
    constructor(private readonly callback: MutationCallback) {
        MockMutationObserver.instances.push(this)
    }
    observe(): void {}
    disconnect(): void {}
    takeRecords(): MutationRecord[] {
        return []
    }
    trigger(): void {
        this.callback([], this as unknown as MutationObserver)
    }
}

function userMessage(id: string, content: string): ConversationItem {
    return { type: 'user_message', id, content, timestamp: 1 }
}

function Harness({
    items,
    listRef,
}: {
    items: ConversationItem[]
    listRef: MutableRefObject<VirtualizedListHandle | null>
}): JSX.Element {
    const rootRef = useRef<HTMLDivElement>(null)
    return (
        <div ref={rootRef}>
            <div data-attr="virtualized-list-scroll">
                {items.map((item) => (
                    <div key={item.id} data-conversation-item-id={item.id}>
                        {item.type === 'user_message' ? item.content : ''}
                    </div>
                ))}
            </div>
            <ConversationSearchBar items={items} rootRef={rootRef} listRef={listRef} defaultOpen />
        </div>
    )
}

describe('ConversationSearchBar', () => {
    const globals = globalThis as unknown as Record<string, unknown>
    let originalMutationObserver: unknown
    let originalHighlight: unknown
    let originalHighlights: unknown

    beforeAll(() => {
        originalMutationObserver = globals.MutationObserver
        originalHighlight = globals.Highlight
        globals.MutationObserver = MockMutationObserver
        globals.Highlight = MockHighlight
        if (typeof globals.CSS === 'undefined') {
            globals.CSS = {}
        }
        originalHighlights = (globals.CSS as Record<string, unknown>).highlights
        ;(globals.CSS as Record<string, unknown>).highlights = new Map()
    })

    afterAll(() => {
        globals.MutationObserver = originalMutationObserver
        globals.Highlight = originalHighlight
        ;(globals.CSS as Record<string, unknown>).highlights = originalHighlights
    })

    beforeEach(() => {
        MockMutationObserver.instances = []
        ;((globals.CSS as Record<string, unknown>).highlights as Map<string, unknown>).clear()
    })

    afterEach(() => {
        cleanup()
    })

    function makeListRef(): { listRef: MutableRefObject<VirtualizedListHandle | null>; scrollToIndex: jest.Mock } {
        const scrollToIndex = jest.fn()
        return { listRef: { current: { scrollToBottom: jest.fn(), scrollToIndex } }, scrollToIndex }
    }

    function typeQuery(value: string): void {
        fireEvent.change(screen.getByPlaceholderText('Find in conversation...'), { target: { value } })
    }

    it('navigates matches and clamps the cursor when matches shrink mid-stream', () => {
        const { listRef, scrollToIndex } = makeListRef()
        const items = [userMessage('a', 'alpha foo'), userMessage('b', 'bar'), userMessage('c', 'foo baz')]
        const view = render(<Harness items={items} listRef={listRef} />)

        typeQuery('foo')
        expect(screen.getByText('1 of 2')).toBeTruthy()
        expect(scrollToIndex).toHaveBeenCalledWith(0)

        fireEvent.click(screen.getByLabelText('Next match'))
        expect(screen.getByText('2 of 2')).toBeTruthy()
        expect(scrollToIndex).toHaveBeenLastCalledWith(2)

        // The last item stops matching while the cursor sits on it.
        const shrunk = [userMessage('a', 'alpha foo'), userMessage('b', 'bar'), userMessage('c', 'qux')]
        view.rerender(<Harness items={shrunk} listRef={listRef} />)
        expect(screen.getByText('1 of 1')).toBeTruthy()

        fireEvent.click(screen.getByLabelText('Next match'))
        expect(screen.getByText('1 of 1')).toBeTruthy()
        expect(scrollToIndex).toHaveBeenLastCalledWith(0)
    })

    it('shows no results and skips navigation when every match disappears', () => {
        const { listRef, scrollToIndex } = makeListRef()
        const view = render(<Harness items={[userMessage('a', 'alpha foo')]} listRef={listRef} />)

        typeQuery('foo')
        expect(screen.getByText('1 of 1')).toBeTruthy()
        const callsBefore = scrollToIndex.mock.calls.length

        view.rerender(<Harness items={[userMessage('a', 'alpha')]} listRef={listRef} />)
        expect(screen.getByText('No results')).toBeTruthy()

        fireEvent.click(screen.getByLabelText('Next match'))
        expect(scrollToIndex.mock.calls.length).toBe(callsBefore)
    })

    it('keeps a single MutationObserver across match navigation and streaming updates', () => {
        const { listRef } = makeListRef()
        const items = [userMessage('a', 'alpha foo'), userMessage('b', 'foo baz')]
        const view = render(<Harness items={items} listRef={listRef} />)
        expect(MockMutationObserver.instances).toHaveLength(1)

        typeQuery('foo')
        fireEvent.click(screen.getByLabelText('Next match'))
        fireEvent.click(screen.getByLabelText('Previous match'))
        view.rerender(<Harness items={[...items, userMessage('c', 'more foo')]} listRef={listRef} />)

        expect(MockMutationObserver.instances).toHaveLength(1)
    })

    it('applies highlights for the current query and reapplies them when the observer fires', () => {
        const { listRef } = makeListRef()
        render(<Harness items={[userMessage('a', 'alpha foo')]} listRef={listRef} />)
        const highlights = (globals.CSS as Record<string, unknown>).highlights as Map<string, unknown>

        typeQuery('foo')
        expect(highlights.has('search-match')).toBe(true)
        expect(highlights.has('search-match-active')).toBe(true)

        highlights.clear()
        MockMutationObserver.instances[0].trigger()
        expect(highlights.has('search-match')).toBe(true)
    })
})
