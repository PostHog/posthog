import {
    createContext,
    CSSProperties,
    ReactNode,
    UIEvent,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useRef,
} from 'react'
import { List, RowComponentProps, useDynamicRowHeight, useListRef } from 'react-window'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'
import { cn } from 'lib/utils/css-classes'

/** Within this many px of the bottom still counts as "pinned" — absorbs iOS momentum/rubber-band jitter. */
const BOTTOM_THRESHOLD = 32

/**
 * At or within this many px of the bottom counts as "already there", so `maybeStickToBottom` skips re-issuing
 * a scroll — doing so at the final position cancels macOS's native overscroll bounce and reads as a shake.
 * Kept tiny (a scroll snaps exactly to the bottom, so a resting reader is at distance 0); just wide enough to
 * absorb fractional-pixel scroll positions. Growth past this still re-pins to the true bottom.
 */
const AT_BOTTOM_EPSILON = 2

/**
 * Frames the initial settle-to-bottom keeps re-issuing the scroll. With variable row heights a single
 * scroll on first content lands short (rows below the fold are estimated until rendered + measured), so a
 * freshly refreshed/opened thread needs a few correction frames to reach the true bottom. Bounded so a
 * never-settling layout can't loop forever.
 */
const MAX_INITIAL_SCROLL_FRAMES = 30

const EMPTY_STYLE: CSSProperties = {}
const EMPTY_ARIA: Record<string, unknown> = {}

interface RootContextValue {
    dynamicRowHeight: ReturnType<typeof useDynamicRowHeight>
    /** Inter-row spacing (px), applied as bottom padding on the measured row so heights include it. */
    gap: number
    maxWidthClassName: string
    /** When false, rows render in document flow (no react-window) and an ancestor owns scroll. */
    virtualized: boolean
}

interface RowContextValue {
    index: number
    style: CSSProperties
    ariaAttributes: Record<string, unknown>
}

const RootContext = createContext<RootContextValue | null>(null)
const RowContext = createContext<RowContextValue | null>(null)

interface InternalRowProps {
    renderRow: (index: number) => ReactNode
}

/** react-window row shell: publishes per-row positioning via context and defers content to `renderRow`. */
function InternalRow({ index, style, ariaAttributes, renderRow }: RowComponentProps<InternalRowProps>): JSX.Element {
    const value = useMemo<RowContextValue>(() => ({ index, style, ariaAttributes }), [index, style, ariaAttributes])
    return <RowContext.Provider value={value}>{renderRow(index)}</RowContext.Provider>
}

export interface VirtualizedThreadRootProps<T> {
    items: T[]
    /** Stable key per item — used for stick-to-bottom change detection (react-window keys rows by index). */
    getItemKey: (item: T, index: number) => string
    /** Rendered as a measured leading row (e.g. run context). */
    header?: ReactNode
    /** Rendered as a measured trailing row (e.g. thinking indicator, PR card). */
    footer?: ReactNode
    /** Inter-row spacing in px (default 6, matching `gap-1.5`). */
    gap?: number
    /** Height used until a row is measured. */
    defaultRowHeight?: number
    overscanCount?: number
    /** Follow the bottom as rows grow/append; unpins when the user scrolls up. */
    stickToBottom?: boolean
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
 * Embeddable virtualized thread. Fills any height-bounded parent (`h-full`/`flex-1 min-h-0`/fixed) via
 * `AutoSizer`, virtualizes rows with react-window, measures dynamic heights, owns its own scroll and an
 * optional stick-to-bottom that follows streaming growth. Render rows through the `children` render-prop,
 * each wrapped in `VirtualizedThread.Row`.
 */
function Root<T>({
    items,
    getItemKey,
    header,
    footer,
    gap = 6,
    defaultRowHeight = 56,
    overscanCount = 10,
    stickToBottom = true,
    maxWidthClassName = 'max-w-180',
    className,
    listClassName,
    virtualized = true,
    children,
}: VirtualizedThreadRootProps<T>): JSX.Element {
    // Shared per-row height cache (Map keyed by row index). Survives re-renders and react-window's
    // row recycling, so scrolling back to an already-measured row reuses its height without a flash;
    // rows are re-measured on resize via `observeRowElements` (see `Row`).
    const dynamicRowHeight = useDynamicRowHeight({ defaultRowHeight })
    const listRef = useListRef(null)

    const hasHeader = header != null
    const hasFooter = footer != null
    const rowCount = items.length + (hasHeader ? 1 : 0) + (hasFooter ? 1 : 0)

    const pinnedRef = useRef(stickToBottom)
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

    const scrollToBottom = useCallback((): void => {
        if (rowCount === 0) {
            return
        }
        listRef.current?.scrollToRow({ index: rowCount - 1, align: 'end' })
        // `scrollToRow` lands a hair short with dynamic row heights, leaving the last line a few px out of
        // view; snap to the exact maximum (the browser clamps `scrollTop` to its valid range).
        const el = listRef.current?.element
        if (el) {
            el.scrollTop = el.scrollHeight
        }
    }, [listRef, rowCount])

    // Re-assert the bottom only when content has pushed it out of view (streaming growth, measurement
    // settle, initial open) — so the open scroll converges to the true bottom as rows are measured, while
    // a user resting at the final position is left alone. Skipping when already there is what stops the
    // re-issued scroll from cancelling macOS's native overscroll bounce (the "shake"). No element yet (the
    // first pass before mount) ⇒ scroll unconditionally.
    const maybeStickToBottom = useCallback((): void => {
        if (!stickToBottom || !pinnedRef.current) {
            return
        }
        const el = listRef.current?.element
        if (el && el.scrollHeight - el.scrollTop - el.clientHeight <= AT_BOTTOM_EPSILON) {
            return
        }
        scrollToBottom()
    }, [stickToBottom, scrollToBottom, listRef])

    const handleScroll = useCallback(
        (event: UIEvent<HTMLDivElement>): void => {
            if (!stickToBottom) {
                return
            }
            const el = event.currentTarget
            pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_THRESHOLD
        },
        [stickToBottom]
    )

    const handleRowsRendered = useCallback((): void => {
        maybeStickToBottom()
    }, [maybeStickToBottom])

    // Re-pin as content appends/streams and as dynamic measurements settle — gated by `maybeStickToBottom`
    // so it scrolls only while the bottom is out of view. Pinned by default, so this also scrolls to the
    // bottom on open: the first pass fires before rows are measured (they start at `defaultRowHeight`) and
    // lands short, then re-fires as ResizeObserver grows the rows until it settles at the true bottom.
    const lastKey = items.length > 0 ? getItemKey(items[items.length - 1], items.length - 1) : null
    const measuredAverageHeight = dynamicRowHeight.getAverageRowHeight()
    useEffect(() => {
        if (!virtualized || !stickToBottom || !pinnedRef.current) {
            return
        }
        const raf = requestAnimationFrame(maybeStickToBottom)
        return () => cancelAnimationFrame(raf)
    }, [virtualized, stickToBottom, maybeStickToBottom, rowCount, lastKey, measuredAverageHeight])

    // First content (open / hard refresh): drive the scroll to the true bottom across a few frames. The
    // per-dep effect above fires too few times as the list mounts and rows measure, so a single pass lands
    // short of the last messages. Re-pin first so a stray load-time scroll event can't leave it unpinned,
    // then re-issue until actually at the bottom (or the frame budget runs out). Runs once; streaming
    // growth afterwards is the per-dep effect's job.
    useEffect(() => {
        if (!virtualized || !stickToBottom || didInitialScrollRef.current || rowCount === 0) {
            return
        }
        didInitialScrollRef.current = true
        pinnedRef.current = true
        let frame = 0
        let lastHeight = -1
        let raf = requestAnimationFrame(function settle(): void {
            scrollToBottom()
            frame += 1
            // Each pass snaps to the exact current bottom; keep going while measurements still grow the
            // content, and stop once the height holds steady (we're at the true bottom) or the budget runs
            // out. Terminating on height — not distance — is what avoids stopping a few px short before the
            // rows below the fold have finished measuring.
            const height = listRef.current?.element?.scrollHeight ?? 0
            if (height !== lastHeight && frame < MAX_INITIAL_SCROLL_FRAMES) {
                lastHeight = height
                raf = requestAnimationFrame(settle)
            }
        })
        return () => cancelAnimationFrame(raf)
    }, [virtualized, stickToBottom, rowCount, scrollToBottom, listRef])

    // Mobile Safari: the soft keyboard shrinks the visual (not layout) viewport, so a pinned bottom can
    // slip behind it. Re-assert on visualViewport changes.
    useEffect(() => {
        if (!virtualized || !stickToBottom || typeof window === 'undefined' || !window.visualViewport) {
            return
        }
        const viewport = window.visualViewport
        const onViewportChange = (): void => {
            if (pinnedRef.current) {
                requestAnimationFrame(scrollToBottom)
            }
        }
        viewport.addEventListener('resize', onViewportChange)
        viewport.addEventListener('scroll', onViewportChange)
        return () => {
            viewport.removeEventListener('resize', onViewportChange)
            viewport.removeEventListener('scroll', onViewportChange)
        }
    }, [virtualized, stickToBottom, scrollToBottom])

    const rootValue = useMemo<RootContextValue>(
        () => ({ dynamicRowHeight, gap, maxWidthClassName, virtualized }),
        [dynamicRowHeight, gap, maxWidthClassName, virtualized]
    )

    // Flow mode: render rows directly so an ancestor scroll container (and its auto-scroller) keeps working.
    // No chrome here — the parent supplies gap/centering/container-query context, matching the pre-virtualized
    // layout exactly.
    if (!virtualized) {
        return (
            <RootContext.Provider value={rootValue}>
                {hasHeader && (
                    <RowContext.Provider
                        key="header"
                        value={{ index: 0, style: EMPTY_STYLE, ariaAttributes: EMPTY_ARIA }}
                    >
                        {header}
                    </RowContext.Provider>
                )}
                {items.map((item, index) => (
                    <RowContext.Provider
                        key={getItemKey(item, index)}
                        value={{ index, style: EMPTY_STYLE, ariaAttributes: EMPTY_ARIA }}
                    >
                        {children(item, index)}
                    </RowContext.Provider>
                ))}
                {hasFooter && (
                    <RowContext.Provider
                        key="footer"
                        value={{ index: rowCount - 1, style: EMPTY_STYLE, ariaAttributes: EMPTY_ARIA }}
                    >
                        {footer}
                    </RowContext.Provider>
                )}
            </RootContext.Provider>
        )
    }

    return (
        <RootContext.Provider value={rootValue}>
            <div className={cn('flex flex-col h-full min-h-0 w-full', className)}>
                <AutoSizer
                    renderProp={({ height, width }: SizeProps) => {
                        if (!height || !width) {
                            return null
                        }
                        // react-window sets only `overflowY: auto`, which makes the unset `overflow-x` compute
                        // to `auto` too — pin it to `hidden` so the thread never scrolls sideways (wide blocks
                        // like tool output scroll within their own containers).
                        return (
                            <List<InternalRowProps>
                                style={{ height, width, overflowX: 'hidden' }}
                                className={cn('overscroll-contain', listClassName)}
                                overscanCount={overscanCount}
                                rowCount={rowCount}
                                rowHeight={dynamicRowHeight}
                                rowComponent={InternalRow}
                                rowProps={{ renderRow }}
                                listRef={listRef}
                                onRowsRendered={handleRowsRendered}
                                onScroll={handleScroll}
                            />
                        )
                    }}
                />
            </div>
        </RootContext.Provider>
    )
}

/**
 * Row shell for content rendered inside `VirtualizedThread.Root`. Applies react-window positioning, measures
 * its own height (gap included via bottom padding), and centers content with the thread's container-query context.
 */
function Row({ children, className }: { children: ReactNode; className?: string }): JSX.Element {
    const root = useContext(RootContext)
    const row = useContext(RowContext)
    if (!root || !row) {
        throw new Error('VirtualizedThread.Row must be rendered inside VirtualizedThread.Root')
    }
    const { dynamicRowHeight, gap, maxWidthClassName, virtualized } = root
    const { style, ariaAttributes, index } = row
    const rowRef = useRef<HTMLDivElement>(null)

    // Cache + recalc: `observeRowElements` attaches a ResizeObserver to the measured row element and
    // writes its border-box height into the shared cache. So when this row's content changes height —
    // tool output expand/collapse, streaming markdown, a late-loading image — it is re-measured and the
    // list re-lays-out automatically. We observe the outer element (which is never given a fixed height,
    // only react-window's position/transform), and the gap padding lives on its child, so the cached
    // height always includes inter-row spacing and content growth.
    useEffect(() => {
        if (virtualized && rowRef.current) {
            return dynamicRowHeight.observeRowElements([rowRef.current])
        }
    }, [virtualized, dynamicRowHeight])

    // Flow mode: transparent — the parent container provides spacing and centering.
    if (!virtualized) {
        return <>{children}</>
    }

    return (
        <div ref={rowRef} style={style} data-index={index} {...ariaAttributes}>
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
