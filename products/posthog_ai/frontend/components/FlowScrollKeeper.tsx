import { Component, createRef } from 'react'

function findScrollParent(node: Element): HTMLElement | null {
    let current = node.parentElement
    while (current) {
        const { overflowY } = getComputedStyle(current)
        if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') {
            return current
        }
        current = current.parentElement
    }
    return document.scrollingElement instanceof HTMLElement ? document.scrollingElement : null
}

/** The first element in `parent` whose bottom edge is below `viewportTop`. Rows stack in document order. */
function findFirstVisibleChild(parent: Element, viewportTop: number): Element | null {
    const children = parent.children
    let low = 0
    let high = children.length - 1
    let found: Element | null = null
    while (low <= high) {
        const middle = (low + high) >> 1
        let probe = middle
        // Hidden elements have an empty rect, so the search reads the next element in the DOM.
        while (probe <= high && children[probe].getClientRects().length === 0) {
            probe++
        }
        if (probe > high) {
            high = middle - 1
            continue
        }
        if (children[probe].getBoundingClientRect().bottom > viewportTop) {
            found = children[probe]
            high = middle - 1
        } else {
            low = probe + 1
        }
    }
    return found
}

interface FlowScrollKeeperProps {
    fillStep: number
    /** The fill step rendered the oldest rows for a reader who went to the top, so the view goes to the top. */
    holdTop: boolean
    filling: boolean
}

interface FlowScrollSnapshot {
    scroller: HTMLElement
    atTop: boolean
    atBottom: boolean
    anchor: Element | null
    anchorTop: number
}

/**
 * Keeps the reader's view in place while a fill step adds older rows above it. Before the commit it
 * notes the first row in view, and after the commit it scrolls by the distance that row moved. Growth
 * below that row, such as a streamed reply, does not move it, so it does not move the view.
 *
 * A reader at the bottom stays at the bottom. A fill step that renders the oldest rows for a reader who
 * went to the top puts the view at the top, so the reader sees the start of the thread.
 */
export class FlowScrollKeeper extends Component<FlowScrollKeeperProps> {
    private sentinel = createRef<HTMLSpanElement>()
    // The browser rounds `scrollTop`. Carrying the rounding into the next step stops a long fill from drifting.
    private remainder = 0

    override getSnapshotBeforeUpdate(previous: Readonly<FlowScrollKeeperProps>): FlowScrollSnapshot | null {
        const sentinel = this.sentinel.current
        if (this.props.fillStep === previous.fillStep || !sentinel?.parentElement) {
            return null
        }
        const scroller = findScrollParent(sentinel)
        if (!scroller) {
            return null
        }
        if (this.props.holdTop) {
            return { scroller, atTop: true, atBottom: false, anchor: null, anchorTop: 0 }
        }
        if (scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 1) {
            return { scroller, atTop: false, atBottom: true, anchor: null, anchorTop: 0 }
        }
        const viewportTop = scroller === document.scrollingElement ? 0 : scroller.getBoundingClientRect().top
        const anchor = findFirstVisibleChild(sentinel.parentElement, viewportTop)
        return anchor
            ? { scroller, atTop: false, atBottom: false, anchor, anchorTop: anchor.getBoundingClientRect().top }
            : null
    }

    override componentDidUpdate(
        _previous: Readonly<FlowScrollKeeperProps>,
        _state: unknown,
        snapshot: FlowScrollSnapshot | null
    ): void {
        if (!snapshot) {
            return
        }
        const { scroller, atTop, atBottom, anchor, anchorTop } = snapshot
        if (atTop) {
            scroller.scrollTop = 0
            return
        }
        if (atBottom) {
            scroller.scrollTop = scroller.scrollHeight
            return
        }
        if (!anchor?.isConnected) {
            return
        }
        // Correct from the current position: the browser's own scroll anchoring may already have moved it.
        const target = scroller.scrollTop + anchor.getBoundingClientRect().top - anchorTop + this.remainder
        scroller.scrollTop = target
        this.remainder = Math.max(-1, Math.min(1, target - scroller.scrollTop))
    }

    readerScrollTop(): number | null {
        const sentinel = this.sentinel.current
        const scroller = sentinel ? findScrollParent(sentinel) : null
        return scroller ? scroller.scrollTop : null
    }

    override render(): JSX.Element | null {
        return this.props.filling ? <span hidden ref={this.sentinel} /> : null
    }
}
