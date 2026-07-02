import { useVirtualizer } from '@tanstack/react-virtual'
import {
    createContext,
    CSSProperties,
    memo,
    ReactNode,
    useCallback,
    useContext,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
} from 'react'

import { cn } from 'lib/utils/css-classes'

/** Within this many px of the bottom still counts as "pinned" — absorbs iOS momentum/rubber-band jitter. */
const BOTTOM_THRESHOLD = 32

const EMPTY_STYLE: CSSProperties = {}

/**
 * Virtual keys for the synthetic header/footer rows — reserved prefixes that never collide with a user item
 * key. The footer key is a prefix, not a constant: `getVirtualItemKey` appends the item count to it.
 */
const HEADER_KEY = '__vt_header__'
const FOOTER_KEY = '__vt_footer__'

interface RootContextValue {
    /** The virtualizer's border-box `ResizeObserver` ref — attach to each measured row's outer element. */
    measureElement: (node: Element | null) => void
    /** Inter-row spacing (px), applied as bottom padding on the measured row so heights include it. */
    gap: number
    maxWidthClassName: string
    /** When false, rows render in document flow (no virtualization) and an ancestor owns scroll. */
    virtualized: boolean
}

interface RowContextValue {
    index: number
    style: CSSProperties
}

const RootContext = createContext<RootContextValue | null>(null)
const RowContext = createContext<RowContextValue | null>(null)

/**
 * Virtualized row shell: publishes per-row absolute positioning via context and defers content to
 * `renderRow`. Memoized on the values that actually change so a pure scroll (which shifts the visible
 * window but not a given row's `index`/`start`) doesn't re-render every mounted row.
 */
const InternalRow = memo(function InternalRow({
    index,
    start,
    renderRow,
}: {
    index: number
    start: number
    renderRow: (index: number) => ReactNode
}): JSX.Element {
    const style = useMemo<CSSProperties>(
        () => ({ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${start}px)` }),
        [start]
    )
    const value = useMemo<RowContextValue>(() => ({ index, style }), [index, style])
    return <RowContext.Provider value={value}>{renderRow(index)}</RowContext.Provider>
})

export interface VirtualizedThreadRootProps<T> {
    items: T[]
    /** Stable key per item — keys the measurement cache (correct reuse on prepend/reorder). */
    getItemKey: (item: T, index: number) => string
    /** Rendered as a measured leading row (e.g. run context). */
    header?: ReactNode
    /** Rendered as a measured trailing row (e.g. thinking indicator, PR card). */
    footer?: ReactNode
    /** Inter-row spacing in px (default 6, matching `gap-1.5`). */
    gap?: number
    /** Height used until a row is measured. */
    defaultRowHeight?: number
    /**
     * Per-item pre-measurement height estimate in px (gap excluded — added internally). The closer the
     * estimate to the real row height, the smaller the scroll-position correction applied when an
     * unmeasured row above the viewport gets its first measurement — which is what makes scrolling up
     * through unvisited history feel like dragging. Falls back to `defaultRowHeight`.
     */
    estimateItemHeight?: (item: T, index: number) => number
    overscanCount?: number
    /** Follow the bottom as rows grow/append; unpins when the user scrolls up. */
    stickToBottom?: boolean
    /**
     * Item index (0-based within `items`) to align to the top of the viewport on the initial open,
     * instead of scrolling to the bottom — e.g. open a task thread at its last user message. The thread
     * is left unpinned so stick-to-bottom doesn't immediately pull it back down. `null`/omitted keeps the
     * default open-at-bottom behavior. Consumed once, on first content; later changes are ignored.
     */
    initialTopItemIndex?: number | null
    maxWidthClassName?: string
    className?: string
    /**
     * Virtualize and own scroll (default `true` — requires a height-bounded parent). Pass `false` to render
     * rows in document flow and let an ancestor own the scroll (e.g. an external auto-scroller); the wrapper
     * adds no chrome in this mode, so the parent supplies layout (gap, centering, container query).
     */
    virtualized?: boolean
    listClassName?: string
    children: (item: T, index: number) => ReactNode
}

/**
 * Embeddable virtualized thread. Fills any height-bounded parent (`h-full`/`flex-1 min-h-0`/fixed),
 * virtualizes rows with TanStack Virtual, measures dynamic heights, owns its own scroll and an optional
 * stick-to-bottom that follows streaming growth. Render rows through the `children` render-prop, each
 * wrapped in `VirtualizedThread.Row`.
 */
function Root<T>({
    items,
    getItemKey,
    header,
    footer,
    gap = 6,
    defaultRowHeight = 56,
    estimateItemHeight,
    overscanCount = 10,
    stickToBottom = true,
    initialTopItemIndex = null,
    maxWidthClassName = 'max-w-180',
    className,
    listClassName,
    virtualized = true,
    children,
}: VirtualizedThreadRootProps<T>): JSX.Element {
    const hasHeader = header != null
    const hasFooter = footer != null
    const rowCount = items.length + (hasHeader ? 1 : 0) + (hasFooter ? 1 : 0)

    const scrollRef = useRef<HTMLDivElement>(null)
    const didInitialScrollRef = useRef(false)

    const renderRow = useCallback(
        (index: number): ReactNode => {
            let i = index
            if (hasHeader) {
                if (i === 0) {
                    return header
                }
                i -= 1
            }
            if (i < items.length) {
                return children(items[i], i)
            }
            return footer
        },
        [items, header, footer, hasHeader, children]
    )

    // Wrap the user key with the header/footer offset so measurement is cached by a stable key: prepends and
    // replay-reorders reuse a row's measured height instead of re-measuring by index.
    const getVirtualItemKey = useCallback(
        (index: number): string => {
            let i = index
            if (hasHeader) {
                if (i === 0) {
                    return HEADER_KEY
                }
                i -= 1
            }
            if (i < items.length) {
                return getItemKey(items[i], i)
            }
            // The item count rides in the footer key: TanStack detects "append at the end" (the
            // `followOnAppend` stick) by a last-key change, and a constant footer key would mask every item
            // append behind it — count grows, last key stays the footer — silently breaking follow while the
            // footer (the streaming case's thinking indicator) is visible. The cost is one estimate-sized
            // frame per append while the always-mounted footer re-measures under its new key.
            return `${FOOTER_KEY}${items.length}`
        },
        [items, getItemKey, hasHeader]
    )

    // Measured heights include the gap padding (see `Row`), so estimates must too — otherwise every first
    // measurement carries a built-in error that gets compensated as a scroll-position correction.
    const estimateVirtualRow = useCallback(
        (index: number): number => {
            let i = index
            if (hasHeader) {
                if (i === 0) {
                    return defaultRowHeight + gap
                }
                i -= 1
            }
            if (i < items.length) {
                return (estimateItemHeight?.(items[i], i) ?? defaultRowHeight) + gap
            }
            return defaultRowHeight + gap
        },
        [items, hasHeader, estimateItemHeight, defaultRowHeight, gap]
    )

    const virtualizer = useVirtualizer({
        count: rowCount,
        getScrollElement: () => scrollRef.current,
        estimateSize: estimateVirtualRow,
        overscan: overscanCount,
        getItemKey: getVirtualItemKey,
        // No `gap` — inter-row spacing is baked into the measured row height via `paddingBottom` (see `Row`).
        ...(stickToBottom
            ? {
                  // The core owns stick-to-bottom entirely: `anchorTo: 'end'` re-anchors on count/edge-key
                  // change (append/prepend/reorder), `followOnAppend` scrolls to new rows when at the end,
                  // and the core's resize handling compensates height-only growth (token streaming) while
                  // within `scrollEndThreshold` of the end — and stops the moment the user scrolls away.
                  anchorTo: 'end' as const,
                  followOnAppend: 'auto' as const,
                  scrollEndThreshold: BOTTOM_THRESHOLD,
                  // Seed the virtual offset past the end so the very first render window already emits the
                  // bottom rows (not a blank top frame); the pre-paint `scrollToIndex` below lands them
                  // exactly in view. Summing the row estimates keeps this exact whatever `estimateItemHeight`
                  // returns — a flat multiplier would undershoot and flash a mid-thread window.
                  initialOffset: () => {
                      let total = 0
                      for (let i = 0; i < rowCount; i++) {
                          total += estimateVirtualRow(i)
                      }
                      return total
                  },
              }
            : {}),
    })

    // Initial open (once): land at the last row before the browser paints, so a long thread never shows a
    // top-frame flicker or a visible crawl. `initialOffset` makes render #1 already emit the bottom window;
    // this pre-paint `scrollToIndex` snaps to the exact bottom, and TanStack's built-in RAF reconciliation
    // corrects the landing as rows below the fold measure — replacing the old settle loop.
    useLayoutEffect(() => {
        if (!virtualized || !stickToBottom || didInitialScrollRef.current || rowCount === 0) {
            return
        }
        didInitialScrollRef.current = true
        virtualizer.scrollToIndex(rowCount - 1, { align: 'end' })
    }, [virtualized, stickToBottom, rowCount, virtualizer])

    // Mobile Safari: the soft keyboard shrinks the visual (not layout) viewport, so a pinned bottom can slip
    // behind it. Re-assert on visualViewport changes.
    useEffect(() => {
        if (!virtualized || !stickToBottom || typeof window === 'undefined' || !window.visualViewport) {
            return
        }
        const viewport = window.visualViewport
        const onViewportChange = (): void => {
            if (virtualizer.isAtEnd(BOTTOM_THRESHOLD)) {
                requestAnimationFrame(() => virtualizer.scrollToEnd())
            }
        }
        viewport.addEventListener('resize', onViewportChange)
        viewport.addEventListener('scroll', onViewportChange)
        return () => {
            viewport.removeEventListener('resize', onViewportChange)
            viewport.removeEventListener('scroll', onViewportChange)
        }
    }, [virtualized, stickToBottom, virtualizer])

    const rootValue = useMemo<RootContextValue>(
        () => ({ measureElement: virtualizer.measureElement, gap, maxWidthClassName, virtualized }),
        [virtualizer, gap, maxWidthClassName, virtualized]
    )

    // Flow mode: render rows directly so an ancestor scroll container (and its auto-scroller) keeps working.
    // No chrome here — the parent supplies gap/centering/container-query context, matching the pre-virtualized
    // layout exactly.
    if (!virtualized) {
        return (
            <RootContext.Provider value={rootValue}>
                {hasHeader && (
                    <RowContext.Provider key="header" value={{ index: 0, style: EMPTY_STYLE }}>
                        {header}
                    </RowContext.Provider>
                )}
                {items.map((item, index) => (
                    <RowContext.Provider key={getItemKey(item, index)} value={{ index, style: EMPTY_STYLE }}>
                        {children(item, index)}
                    </RowContext.Provider>
                ))}
                {hasFooter && (
                    <RowContext.Provider key="footer" value={{ index: rowCount - 1, style: EMPTY_STYLE }}>
                        {footer}
                    </RowContext.Provider>
                )}
            </RootContext.Provider>
        )
    }

    return (
        <RootContext.Provider value={rootValue}>
            <div className={cn('flex flex-col h-full min-h-0 w-full', className)}>
                <div
                    ref={scrollRef}
                    className={cn('flex-1 min-h-0 overflow-y-auto overflow-x-hidden overscroll-contain', listClassName)}
                >
                    <div style={{ height: virtualizer.getTotalSize(), width: '100%', position: 'relative' }}>
                        {virtualizer.getVirtualItems().map((vi) => {
                            const key = String(vi.key)
                            return (
                                <InternalRow
                                    // The footer's virtual key rotates per append (see `getVirtualItemKey`) but its React
                                    // identity must not — remounting it would reset footer-local state (e.g. the thinking
                                    // indicator's rotation timer) on every appended row.
                                    key={key.startsWith(FOOTER_KEY) ? FOOTER_KEY : key}
                                    index={vi.index}
                                    start={vi.start}
                                    renderRow={renderRow}
                                />
                            )
                        })}
                    </div>
                </div>
            </div>
        </RootContext.Provider>
    )
}

/**
 * Row shell for content rendered inside `VirtualizedThread.Root`. Applies the virtualizer's absolute
 * positioning, measures its own height (gap included via bottom padding), and centers content with the
 * thread's container-query context.
 */
function Row({ children, className }: { children: ReactNode; className?: string }): JSX.Element {
    const root = useContext(RootContext)
    const row = useContext(RowContext)
    if (!root || !row) {
        throw new Error('VirtualizedThread.Row must be rendered inside VirtualizedThread.Root')
    }
    const { measureElement, gap, maxWidthClassName, virtualized } = root
    const { style, index } = row

    // Flow mode: transparent — the parent container provides spacing and centering.
    if (!virtualized) {
        return <>{children}</>
    }

    // The outer element carries only positioning (never a fixed height); TanStack's `measureElement` attaches
    // a border-box `ResizeObserver` to it (keyed by `data-index`), so the cached height always tracks content
    // growth — tool output expand/collapse, streaming markdown, a late-loading image — and includes the gap
    // padding on the child. Border-box measurement is transform-safe, so the `translateY` positioning above
    // does not distort it.
    return (
        <div ref={measureElement} data-index={index} style={style}>
            <div
                className={cn('w-full mx-auto @container/thread', maxWidthClassName, className)}
                style={{ paddingBottom: gap }}
            >
                {children}
            </div>
        </div>
    )
}

export const VirtualizedThread = { Root, Row }
