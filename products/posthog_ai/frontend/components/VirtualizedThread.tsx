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
    useState,
} from 'react'

import { cn } from 'lib/utils/css-classes'

/** Within this many px of the bottom still counts as "pinned" — absorbs iOS momentum/rubber-band jitter. */
const BOTTOM_THRESHOLD = 32

/**
 * Static base for measured rows under `directDomUpdates`: the virtualizer writes each row's `translate3d`
 * (and the container's height) directly to the DOM, so React renders no per-row offset at all — a pure
 * scroll or a measurement settle repositions rows without re-rendering them.
 */
const ROW_BASE_STYLE: CSSProperties = { position: 'absolute', top: 0, left: 0, width: '100%' }

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
}

const RootContext = createContext<RootContextValue | null>(null)
const RowContext = createContext<RowContextValue | null>(null)

/**
 * Virtualized row shell: publishes the row index via context and defers content to `renderRow`. Row
 * offsets never pass through React (`directDomUpdates` writes them straight to the DOM), so a mounted row
 * only re-renders when its index or content changes — never on scroll or measurement.
 */
const InternalRow = memo(function InternalRow({
    index,
    renderRow,
}: {
    index: number
    renderRow: (index: number) => ReactNode
}): JSX.Element {
    const value = useMemo<RowContextValue>(() => ({ index }), [index])
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
     * True while the agent is actively working a turn (streaming output into the thread). Gates
     * bottom-pinning: while active, the thread opens pinned to the bottom and streamed rows keep pulling
     * the view down — until the user scrolls up, which unpins; a scroll that lands back at the bottom
     * re-pins (only while the turn is active). While inactive, streamed rows never move the view.
     */
    turnActive?: boolean
    /**
     * Key of the row the reader's attention anchors to — the last human message, typically. Two behaviors
     * hang off it. Open (turn not active): the thread opens with this row at the top of the viewport (the
     * last meaningful turn, its response below) instead of the absolute bottom; clamping degrades to the
     * bottom when little content follows. Change to a new non-null value (a fresh send): the row is
     * scrolled to the top with bottom padding reserved so it can anchor there — the "sent message pins to
     * the top, the response streams into the space below" chat pattern. The reserve shrinks 1:1 as the
     * response streams into it, so the view stays put while the space fills; once the response outgrows
     * the viewport the reserve is gone and stick-to-bottom follows the newest output for the rest of the
     * turn.
     */
    anchorItemKey?: string | null
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
    turnActive = false,
    anchorItemKey,
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
    // Bottom-pinning state (see `turnActive`). Explicit rather than position-derived: during fast
    // streaming the scroll position transiently lags the growing content past any at-bottom threshold,
    // so "is the user at the bottom right now" cannot distinguish "scrolled away" from "content briefly
    // outran the follow scroll". Starts pinned: a thread that opens onto an active turn follows from the
    // first frame, and it stays inert while no turn is active.
    const pinnedRef = useRef(true)
    // Read by the scroll listener without re-subscribing it per render.
    const turnActiveRef = useRef(turnActive)
    turnActiveRef.current = turnActive
    // Bottom padding reserved by the anchor-on-send behavior (`anchorItemKey`), fed to the virtualizer as
    // `paddingEnd`. `undefined` in the prev-key ref means "thread not yet populated".
    const [anchorPadding, setAnchorPadding] = useState(0)
    const prevAnchorKeyRef = useRef<string | null | undefined>(undefined)
    const pendingAnchorScrollRef = useRef<{ index: number; padding: number } | null>(null)

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
            // The item count rides in the footer key: TanStack detects "append at the end" by a last-key
            // change, and a constant footer key would mask every item append behind it — count grows, last
            // key stays the footer — hiding appends from the core's end-anchoring while the footer (the
            // streaming case's thinking indicator) is visible. The cost is one estimate-sized frame per
            // append while the always-mounted footer re-measures under its new key.
            return `${FOOTER_KEY}${items.length}`
        },
        [items, getItemKey, hasHeader]
    )

    const findVirtualIndexForKey = useCallback(
        (key: string): number => {
            // Scan from the end — the anchor (a recent human message) is near the tail in practice.
            for (let i = rowCount - 1; i >= 0; i--) {
                if (getVirtualItemKey(i) === key) {
                    return i
                }
            }
            return -1
        },
        [rowCount, getVirtualItemKey]
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
        paddingEnd: anchorPadding,
        // The virtualizer writes container height + row offsets to the DOM itself, in the same tick as each
        // measurement — no stale-offset overlap while rows measure, and React re-renders only on range change.
        directDomUpdates: true,
        // No `gap` — inter-row spacing is baked into the measured row height via `paddingBottom` (see `Row`).
        ...(stickToBottom
            ? {
                  // `anchorTo: 'end'` re-anchors on count/edge-key change (append/prepend/reorder) and the
                  // core's resize handling compensates height-only growth (token streaming) while within
                  // `scrollEndThreshold` of the end. Bottom-pinning itself is owned by the explicit
                  // pinned-state effects below, not the core (`followOnAppend` stays off). While the send
                  // reserve is up (`anchorPadding > 0`) the core would pin to the *padded* end — scrolling
                  // content up over a blank band — so end-anchoring switches off and the view stays put
                  // while the response streams into the reserved space (see the shrink effect).
                  anchorTo: anchorPadding > 0 ? ('start' as const) : ('end' as const),
                  scrollEndThreshold: BOTTOM_THRESHOLD,
                  // Seed the virtual offset so the very first render window already emits the right rows
                  // (not a blank top frame): the anchor row's estimated start when opening onto an anchor,
                  // past the end for a plain bottom open (which an active turn always uses — see the
                  // initial-open effect). Summing the row estimates keeps this exact whatever
                  // `estimateItemHeight` returns; the pre-paint `scrollToIndex` below lands it.
                  initialOffset: () => {
                      const anchorIndex =
                          !turnActive && anchorItemKey != null ? findVirtualIndexForKey(anchorItemKey) : -1
                      const limit = anchorIndex >= 0 ? anchorIndex : rowCount
                      let total = 0
                      for (let i = 0; i < limit; i++) {
                          total += estimateVirtualRow(i)
                      }
                      return total
                  },
              }
            : {}),
    })

    // Initial open (once): land before the browser paints, so a long thread never shows a top-frame
    // flicker or a visible crawl. An actively-streaming thread opens pinned to the bottom — the turn's
    // newest output — so the reader lands where the action is. A settled thread reopens where the reader
    // left off: with an anchor (the last human message) it opens on the last meaningful turn — anchor row
    // at the top, its response below — not the absolute bottom; scroll clamping degrades this to the
    // bottom when little content follows the anchor. No anchor ⇒ plain bottom open. TanStack's built-in
    // RAF reconciliation holds the landing steady as rows measure — replacing the old settle loop.
    useLayoutEffect(() => {
        if (!virtualized || !stickToBottom || didInitialScrollRef.current || rowCount === 0) {
            return
        }
        didInitialScrollRef.current = true
        const anchorIndex = !turnActive && anchorItemKey != null ? findVirtualIndexForKey(anchorItemKey) : -1
        if (anchorIndex >= 0) {
            virtualizer.scrollToIndex(anchorIndex, { align: 'start' })
        } else {
            virtualizer.scrollToIndex(rowCount - 1, { align: 'end' })
        }
    }, [virtualized, stickToBottom, rowCount, virtualizer, turnActive, anchorItemKey, findVirtualIndexForKey])

    // Anchor-on-change (see `anchorItemKey`): a key change means a new anchor row landed. A *trailing*
    // anchor (nothing after it yet) is a fresh send — reserve enough bottom padding for the row to reach
    // the top of the viewport (via the paired effect below, once the padding is in the DOM) so the
    // response streams into the space below. An anchor that already has content after it (a replayed
    // turn) just scrolls — reserving there would leave dead whitespace under a finished response. The
    // first populated commit only adopts the key: the initial-open effect above owns that scroll.
    useLayoutEffect(() => {
        if (!virtualized || items.length === 0) {
            return
        }
        const prev = prevAnchorKeyRef.current
        if (prev === undefined) {
            prevAnchorKeyRef.current = anchorItemKey ?? null
            return
        }
        if (anchorItemKey == null || anchorItemKey === prev) {
            return
        }
        prevAnchorKeyRef.current = anchorItemKey
        const anchorIndex = findVirtualIndexForKey(anchorItemKey)
        if (anchorIndex < 0) {
            return
        }
        const isTrailingItem = anchorIndex === (hasHeader ? 1 : 0) + items.length - 1
        if (!isTrailingItem) {
            virtualizer.scrollToIndex(anchorIndex, { align: 'start' })
            return
        }
        // `getTotalSize()` first: it recomputes the measurements, so the `measurementsCache` read below
        // reflects this commit's rows (including the anchor row's just-taken first measurement).
        const totalSize = virtualizer.getTotalSize()
        const anchorStart = virtualizer.measurementsCache[anchorIndex]?.start
        const viewport = scrollRef.current?.clientHeight ?? 0
        if (anchorStart === undefined || viewport === 0) {
            return
        }
        // Content below the anchor's top edge, excluding the currently reserved padding — the new reserve
        // must top it up to a full viewport so the anchor row can sit flush at the top.
        const contentBelow = totalSize - anchorPadding - anchorStart
        const padding = Math.max(0, Math.ceil(viewport - contentBelow))
        pendingAnchorScrollRef.current = { index: anchorIndex, padding }
        setAnchorPadding(padding)
    }, [virtualized, items.length, anchorItemKey, findVirtualIndexForKey, virtualizer, anchorPadding, hasHeader])

    // Runs every commit: performs the pending anchor scroll only once the reserved padding is committed to
    // the DOM — scrolling earlier would clamp against the un-padded scroll range and land short of the top.
    useLayoutEffect(() => {
        const pending = pendingAnchorScrollRef.current
        if (!pending || pending.padding !== anchorPadding) {
            return
        }
        pendingAnchorScrollRef.current = null
        virtualizer.scrollToIndex(pending.index, { align: 'start' })
    })

    // Runs every commit while the send reserve is up: shrink it 1:1 as the response streams in. The
    // reserved whitespace is consumed by new content, so the total size — and with it the reader's scroll
    // position — stays put while the response fills the viewport below the anchor. Once content below the
    // anchor exceeds the viewport the reserve is exhausted, the true end is the content end again, and
    // stick-to-bottom takes over for the rest of the turn. Shrink-only on purpose: a row collapsing
    // mid-turn must not re-open whitespace under the thread.
    useLayoutEffect(() => {
        if (!virtualized || anchorPadding <= 0 || pendingAnchorScrollRef.current) {
            return
        }
        const viewport = scrollRef.current?.clientHeight ?? 0
        if (viewport === 0) {
            return
        }
        const anchorKey = prevAnchorKeyRef.current
        const anchorIndex = anchorKey != null ? findVirtualIndexForKey(anchorKey) : -1
        if (anchorIndex < 0) {
            // The anchor row left the thread (reset/replay) — drop the reserve with it.
            setAnchorPadding(0)
            return
        }
        // `getTotalSize()` first: it recomputes the measurements, so the `measurementsCache` read below
        // reflects this commit's rows.
        const totalSize = virtualizer.getTotalSize()
        const anchorStart = virtualizer.measurementsCache[anchorIndex]?.start
        if (anchorStart === undefined) {
            return
        }
        const contentBelow = totalSize - anchorPadding - anchorStart
        const needed = Math.max(0, Math.min(anchorPadding, Math.ceil(viewport - contentBelow)))
        if (needed !== anchorPadding) {
            setAnchorPadding(needed)
        }
    })

    // Pin/unpin from scroll intent, not position: an upward wheel gesture or an offset *decrease*
    // (scrollbar drag, PageUp, touch fling) is the user moving away from the bottom — programmatic follow
    // scrolls only ever move down — so it unpins; a scroll that lands within the bottom threshold re-pins,
    // but only while a turn is active. The wheel listener matters because a scroll event alone can race
    // the per-commit follow write and never surface the decrease. The 4px slack absorbs sub-pixel
    // rounding in the virtualizer's own adjustments.
    useEffect(() => {
        const el = scrollRef.current
        if (!virtualized || !stickToBottom || !el) {
            return
        }
        let prevTop = el.scrollTop
        const onWheel = (event: WheelEvent): void => {
            if (event.deltaY < 0) {
                pinnedRef.current = false
            }
        }
        const onScroll = (): void => {
            const top = el.scrollTop
            if (top < prevTop - 4) {
                pinnedRef.current = false
            } else if (turnActiveRef.current && el.scrollHeight - top - el.clientHeight <= BOTTOM_THRESHOLD) {
                pinnedRef.current = true
            }
            prevTop = top
        }
        el.addEventListener('wheel', onWheel, { passive: true })
        el.addEventListener('scroll', onScroll, { passive: true })
        return () => {
            el.removeEventListener('wheel', onWheel)
            el.removeEventListener('scroll', onScroll)
        }
    }, [virtualized, stickToBottom])

    // Runs every commit: while a turn is active and the reader is pinned, keep the bottom in view. Each
    // streamed frame is a commit, so this needs no other trigger; the core's at-end resize compensation
    // smooths growth that lands between commits. During the send-reserve phase the bottom is the padded
    // end, which the shrink effect holds constant — so this no-ops and the view stays put while the
    // reserved space fills. Writes `scrollTop` directly instead of `scrollToEnd()`: the latter arms the
    // core's multi-frame scroll reconciler, which re-targets the (growing) end every frame and overrides
    // the user's attempt to scroll away — exactly the gesture that must win here.
    useLayoutEffect(() => {
        // A queued anchor scroll (fresh send) owns the next landing — following here would paint one
        // frame at the unpadded end before the anchor scroll pulls the sent message to the top.
        if (!virtualized || !stickToBottom || !turnActive || !pinnedRef.current || pendingAnchorScrollRef.current) {
            return
        }
        const el = scrollRef.current
        if (el && el.scrollHeight - el.scrollTop - el.clientHeight > 1) {
            el.scrollTop = el.scrollHeight
        }
    })

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
                    <RowContext.Provider key="header" value={{ index: 0 }}>
                        {header}
                    </RowContext.Provider>
                )}
                {items.map((item, index) => (
                    <RowContext.Provider key={getItemKey(item, index)} value={{ index }}>
                        {children(item, index)}
                    </RowContext.Provider>
                ))}
                {hasFooter && (
                    <RowContext.Provider key="footer" value={{ index: rowCount - 1 }}>
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
                    {/* Height is written imperatively by the virtualizer (`containerRef` + `directDomUpdates`). */}
                    <div ref={virtualizer.containerRef} style={{ position: 'relative', width: '100%' }}>
                        {virtualizer.getVirtualItems().map((vi) => {
                            const key = String(vi.key)
                            return (
                                <InternalRow
                                    // The footer's virtual key rotates per append (see `getVirtualItemKey`) but its React
                                    // identity must not — remounting it would reset footer-local state (e.g. the thinking
                                    // indicator's rotation timer) on every appended row.
                                    key={key.startsWith(FOOTER_KEY) ? FOOTER_KEY : key}
                                    index={vi.index}
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
 * Row shell for content rendered inside `VirtualizedThread.Root`. Registers itself with the virtualizer
 * (which measures it and positions it directly in the DOM), measures its own height (gap included via
 * bottom padding), and centers content with the thread's container-query context.
 */
function Row({ children, className }: { children: ReactNode; className?: string }): JSX.Element {
    const root = useContext(RootContext)
    const row = useContext(RowContext)
    if (!root || !row) {
        throw new Error('VirtualizedThread.Row must be rendered inside VirtualizedThread.Root')
    }
    const { measureElement, gap, maxWidthClassName, virtualized } = root
    const { index } = row

    // Re-registers the node whenever `index` changes: the virtualizer's element cache (which both direct
    // DOM positioning and measurement read) is addressed by the row's *virtual key*, and a row can change
    // key without remounting — the footer's key rotates on every append. Writing `data-index` here (not as
    // a JSX prop) keeps the attribute and the registration in one atomic step, so the virtualizer never
    // reads a stale index off the node.
    const measureRef = useCallback(
        (node: HTMLDivElement | null): void => {
            if (node) {
                node.setAttribute('data-index', String(index))
            }
            measureElement(node)
        },
        [measureElement, index]
    )

    // Flow mode: transparent — the parent container provides spacing and centering.
    if (!virtualized) {
        return <>{children}</>
    }

    // The outer element carries only the static positioning base (never a fixed height or offset — the
    // virtualizer writes `translate3d` to it directly); TanStack's `measureElement` attaches a border-box
    // `ResizeObserver` to it, so the cached height always tracks content growth — tool output
    // expand/collapse, streaming markdown, a late-loading image — and includes the gap padding on the
    // child. Border-box measurement is transform-safe, so the imperative positioning does not distort it.
    return (
        <div ref={measureRef} style={ROW_BASE_STYLE}>
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
