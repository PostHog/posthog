import { elementScroll, useVirtualizer } from '@tanstack/react-virtual'
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

/**
 * Slack the virtualizer core is allowed to treat as "at the end" while the thread is pinned, so its own
 * growth compensation still smooths streaming that lands between our follow writes. Deliberately *not*
 * used to decide whether the reader is at the bottom — see `AT_BOTTOM_EPSILON`.
 */
const BOTTOM_THRESHOLD = 32

/**
 * `scrollEndThreshold` while unpinned. The core compares it against `getVirtualDistanceFromEnd()`, which
 * clamps at 0 — so 0 would still compensate at the exact end. A negative threshold is the only value that
 * distance can never satisfy, which is what "while the reader is away, no measurement may move the view"
 * requires.
 */
const NO_END_COMPENSATION = -1

/**
 * How close to the bottom the reader has to be to count as *there* — subpixel only. A band here would
 * make the bottom sticky: an upward gesture that stops inside it gets re-pinned and yanked back on the
 * next streamed frame, which reads as the view shaking against the gesture. Zero would be stricter still,
 * but fractional layout/zoom leaves the true bottom a half-pixel short, so re-pinning would be unreachable.
 */
const AT_BOTTOM_EPSILON = 1

/** The core snaps its own scroll writes to within 1.5px of their target — below that is never the reader. */
const UNPIN_SLACK = 1.5

/**
 * How long a recorded programmatic scroll write explains the scroll event it causes. Events land on the
 * next frame; the window only needs to survive frame jank, and staying short keeps a coincidental user
 * scroll to the same offset from being swallowed for long.
 */
const PROGRAMMATIC_SCROLL_MATCH_MS = 200

/**
 * The settle window after an anchor landing: how often and how many times the landing is re-asserted
 * against the anchor's (re-measured) offset. Needed because the core's scroll reconciler has a blind
 * spot — once its target stops moving, an offset nudge from a late row measurement is rewritten by
 * neither of its branches, so it idles to its timeout and leaves the drift in place. Any reader scroll
 * cancels the window immediately.
 */
const ANCHOR_SETTLE_INTERVAL_MS = 250
const ANCHOR_SETTLE_CHECKS = 8

/** Drift below this is indistinguishable from subpixel rounding — not worth a corrective write. */
const ANCHOR_SETTLE_TOLERANCE_PX = 2

/**
 * How long a bottom arrival is ignored by the re-pin test after a programmatic anchor landing. On the
 * landing commit rows are still estimates, so the scroll clamps against a range that grows as rows
 * measure — the settle touches the exact bottom transiently, and each touch emits a scroll event that is
 * indistinguishable from the reader arriving there. Position-based disambiguation is racy (the settle
 * also emits not-at-bottom events between the touches), so the window is temporal: the reconciler holds
 * a stable anchor target within a few frames, and an explicit downward gesture clears the block early.
 */
const BOTTOM_REPIN_BLOCK_MS = 600

/**
 * How long the thread keeps following after a turn reports done. The turn's last rows land after the
 * flag drops: token usage and cost arrive on their own stream frames, and the footer swaps to them a
 * commit or two later. Without the grace that tail renders just below the fold. Overshooting is harmless —
 * an upward gesture unpins instantly, grace or not.
 */
const FOLLOW_GRACE_MS = 1000

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
     * bottom-following: while active, streamed rows keep pulling the view down — as long as the thread is
     * pinned, which it is whenever the reader is at the bottom — until the user scrolls up, which unpins.
     * Unpinning is absolute: nothing moves the view again (not the follow write, not the virtualizer's own
     * growth compensation) until the reader scrolls all the way back to the bottom, which re-pins. Follow
     * outlasts the flag by a moment so the turn's trailing usage/cost row lands in view. While inactive,
     * streamed rows never move the view.
     */
    turnActive?: boolean
    /**
     * Key of the row the reader's attention anchors to — the last human message, typically. Two behaviors
     * hang off it. Open: when at least a viewport of content follows this row, the thread opens with it
     * at the top of the viewport (the last meaningful turn, its response below), mid-turn included; with
     * less content the scroll clamps and the thread opens at the bottom — no padding is ever reserved to
     * force the row higher. Change to a new non-null value (a fresh send): the thread pins to the bottom
     * and follows the streaming answer; the sent message rides up naturally as the response grows.
     */
    anchorItemKey?: string | null
    /**
     * True while `items` are still being assembled (a history replay in flight). Defers the once-only
     * opening scroll and the anchor-key adoption: partial fold commits can carry renderable items —
     * debug/console rows land well before the history's human turns — and spending the open on one of
     * those opens every thread at the bottom instead of its anchor. Cleared-on-error semantics are the
     * caller's job: while true the thread never takes its opening scroll.
     */
    itemsLoading?: boolean
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
    itemsLoading = false,
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
    // first frame, and it stays inert while no turn is active. A ref rather than state because every
    // reader of it needs the value in the same tick as the gesture — the scroll listener, the per-commit
    // follow effect, and the virtualizer options, which `useVirtualizer` re-reads on every render.
    const pinnedRef = useRef(true)
    // Highest offset the reader has reached since the last pin — the yardstick the unpin test measures
    // against. A high-water mark rather than the previous event's offset because a slow drag (scrollbar,
    // touch, a trackpad crawl) moves a couple of px per scroll event and would walk hundreds of px away
    // from the bottom without any single event ever crossing a per-event delta.
    const peakTopRef = useRef(0)
    // Until when bottom arrivals may not re-pin (see `BOTTOM_REPIN_BLOCK_MS`). Armed by programmatic
    // anchor landings; cleared early by an explicit downward gesture.
    const bottomRepinBlockedUntilRef = useRef(0)
    // Recent scroll writes software performed — ours (follow, landings) or the virtualizer core's
    // (`scrollToFn` routes through here). The scroll listener uses them to tell content-driven movement
    // from the reader's: during a fast stream the core writes `scrollTop` many times a frame from its
    // own bookkeeping (measurement compensations, end anchoring), and any of those can move the offset
    // *up* — a lagging internal offset, a row measuring smaller than its estimate — which is byte-for-
    // byte what an upward gesture looks like. The values recorded are the *applied* offsets (read back
    // after the write), so a write the browser clamped still matches its event; a short ring rather
    // than one entry, because a measurement storm can land several writes before their events flush.
    const programmaticScrollsRef = useRef<{ value: number; at: number }[]>([])
    // Item keys of the previous populated commit — how the anchor-change effect tells a fresh send (the
    // key did not exist before) from a replayed anchor (it did). See that effect for why position can't.
    const prevItemKeysRef = useRef<Set<string> | null>(null)
    // When the reader last scrolled (a scroll event no programmatic write explains, or a wheel/touch
    // gesture). The anchor settle loop stands down the moment this passes its start time.
    const lastUserScrollAtRef = useRef(0)
    // The previous scroll event's offset — how the listener recognizes a shrink clamp (see `onScroll`).
    const lastScrollEventTopRef = useRef<number | null>(null)
    // Keeps following for a beat after the turn reports done, so the trailing usage/cost row lands in
    // view (see `FOLLOW_GRACE_MS`).
    const [followGrace, setFollowGrace] = useState(false)
    const prevTurnActiveRef = useRef(turnActive)
    const following = turnActive || followGrace
    // Read by the scroll listener without re-subscribing it per render.
    const followingRef = useRef(following)
    followingRef.current = following
    // Read by the open-decision loop without re-arming it per commit.
    const itemsLengthRef = useRef(items.length)
    itemsLengthRef.current = items.length
    // `undefined` means "thread not yet populated" — the anchor-change effect adopts the first real key.
    const prevAnchorKeyRef = useRef<string | null | undefined>(undefined)

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
            // Constant, and it has to be: the core reads an append off the row *count* alone
            // (`didCountChange || edge keys differ`), so appends reach its end-anchoring without the
            // footer key rotating. Rotating it — which an earlier `followOnAppend` config did need, and
            // that option is off now — charged a scroll correction per appended row: a fresh key misses
            // the measurement cache, the always-mounted footer falls back to `defaultRowHeight` for a
            // frame, and the core's at-end compensation applies that estimate error to the scroll offset.
            // Tens of px of shove per streamed row, right where the reader is trying to scroll away.
            return FOOTER_KEY
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
        // The virtualizer writes container height + row offsets to the DOM itself, in the same tick as each
        // measurement — no stale-offset overlap while rows measure, and React re-renders only on range change.
        directDomUpdates: true,
        // The default `elementScroll`, wrapped so every scroll write the core performs is recorded for
        // the scroll listener's programmatic-vs-reader test (see `programmaticScrollsRef`). Recorded
        // *after* the write, from the element — `scrollTo` applies synchronously, so this is the value
        // the write actually produced, clamping included.
        scrollToFn: (offset, options, instance) => {
            elementScroll(offset, options, instance)
            const applied = instance.scrollElement?.scrollTop ?? offset + (options.adjustments ?? 0)
            const writes = programmaticScrollsRef.current
            writes.push({ value: applied, at: performance.now() })
            if (writes.length > 12) {
                writes.splice(0, writes.length - 12)
            }
        },
        // No `gap` — inter-row spacing is baked into the measured row height via `paddingBottom` (see `Row`).
        ...(stickToBottom
            ? {
                  // `anchorTo: 'end'` re-anchors on count/edge-key change (append/prepend/reorder) and the
                  // core's resize handling compensates height-only growth (token streaming) while within
                  // `scrollEndThreshold` of the end. Bottom-pinning itself is owned by the explicit
                  // pinned-state effects below, not the core (`followOnAppend` stays off). End-anchoring
                  // is strictly a pinned-state behavior: its key/count anchoring applies on every append
                  // with no threshold check, so with it always on, a reader away from the bottom is glued
                  // back to the end whenever rows land — it overrode the opening anchor scroll within
                  // milliseconds while a history replay was still folding in. Off during `itemsLoading`
                  // too: end-anchoring each partial fold walks the core's *internal* offset to the
                  // bottom, and that internal offset only re-syncs via async scroll events — so the
                  // opening anchor scroll lands, the next measurement batch compensates against the
                  // stale bottom offset, and the landing is yanked straight back down.
                  anchorTo: itemsLoading || !pinnedRef.current ? ('start' as const) : ('end' as const),
                  // The core's growth compensation (`resizeItem` re-applying a row's growth to the scroll
                  // offset whenever that offset is within this many px of the end) writes `scrollTop`
                  // synchronously, with no scroll-direction check and no knowledge of our pinned flag. At
                  // 32px that turns the bottom of the thread into flypaper: an upward gesture that stops
                  // inside the band is shoved back down by the next streamed token, the shove arrives as
                  // a downward scroll, and the re-pin test below reads *that* as the reader coming back.
                  // So the band exists only while we consider ourselves pinned, where it does its real
                  // job of smoothing growth that lands between our follow writes; unpinned, nothing but
                  // the reader may move the view — which is also what lets the re-pin test trust downward
                  // motion. Read from the ref, not from state: `useVirtualizer` calls `setOptions` during
                  // render, so the ref applies with no extra render per toggle mid-stream, and `setPinned`
                  // below covers the sub-frame window before that render happens.
                  scrollEndThreshold: pinnedRef.current && !itemsLoading ? BOTTOM_THRESHOLD : NO_END_COMPENSATION,
                  // Seed the virtual offset so the very first render window already emits the right rows
                  // (not a blank top frame): the anchor row's estimated start when opening onto an anchor,
                  // past the end for a plain bottom open. Summing the row estimates keeps this exact
                  // whatever `estimateItemHeight` returns; the pre-paint `scrollToIndex` below lands it.
                  // The seed is the core's *internal* offset only — nothing scrolls the DOM to it — so it
                  // is valid solely when the opening scroll runs in the same commit and converges the two.
                  // Mounting mid-load (the open deferred, the DOM resting at 0) it must be 0: any other
                  // value desyncs internal from DOM, and every first row measurement then "compensates"
                  // the phantom position, deterministically dragging the real scroll toward it.
                  initialOffset: () => {
                      if (itemsLoading) {
                          return 0
                      }
                      const anchorIndex = anchorItemKey != null ? findVirtualIndexForKey(anchorItemKey) : -1
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

    // The only way to flip pinning. Two pins have to move together and in the same tick as the gesture:
    // ours, and the core's at-end growth compensation, which is a second pin we do not otherwise control.
    // Writing the option here is not a duplicate of the render-time value — it is the bridge across one
    // frame. Unpinning originates in a passive wheel/touch/scroll listener, so React schedules the render
    // that would carry the new option for after the current task, while the ResizeObserver that grows the
    // streaming row fires inside it: without this write the core gets one more shove in, on exactly the
    // frame the reader's gesture starts.
    const setPinned = useCallback(
        (next: boolean): void => {
            if (pinnedRef.current === next) {
                return
            }
            pinnedRef.current = next
            virtualizer.options.scrollEndThreshold = next ? BOTTOM_THRESHOLD : NO_END_COMPENSATION
            virtualizer.options.anchorTo = next ? 'end' : 'start'
            if (next) {
                peakTopRef.current = scrollRef.current?.scrollTop ?? 0
            }
        },
        [virtualizer]
    )

    // Every scroll the component performs itself goes through here. The peak records where the *reader*
    // has been, so a landing we caused — a replayed anchor jumping to a row mid-thread, the initial open,
    // a follow write — has to reset it; otherwise the scroll event our own jump emits reads as the reader
    // walking away and unpins on the spot (the slack is sub-pixel, it forgives nothing).
    const noteProgrammaticScroll = useCallback((): void => {
        const top = scrollRef.current?.scrollTop ?? 0
        peakTopRef.current = top
        const writes = programmaticScrollsRef.current
        writes.push({ value: top, at: performance.now() })
        if (writes.length > 12) {
            writes.splice(0, writes.length - 12)
        }
    }, [])

    // Hold an unpinned anchor landing steady while the thread's measurements settle (see the settle
    // constants). Re-asserts via `scrollToIndex` so the corrective write re-computes the offset from the
    // freshest measurements; stands down permanently the moment the reader scrolls or the thread pins
    // (a pinned thread belongs to the follow effect).
    const scheduleAnchorSettle = useCallback(
        (anchorIndex: number): void => {
            const startedAt = performance.now()
            let remaining = ANCHOR_SETTLE_CHECKS
            const tick = (): void => {
                const el = scrollRef.current
                if (!el || lastUserScrollAtRef.current > startedAt || pinnedRef.current) {
                    return
                }
                const target = virtualizer.getOffsetForIndex(anchorIndex, 'start')?.[0]
                if (target !== undefined && Math.abs(el.scrollTop - target) > ANCHOR_SETTLE_TOLERANCE_PX) {
                    virtualizer.scrollToIndex(anchorIndex, { align: 'start' })
                    noteProgrammaticScroll()
                }
                remaining -= 1
                if (remaining > 0) {
                    setTimeout(tick, ANCHOR_SETTLE_INTERVAL_MS)
                }
            }
            setTimeout(tick, ANCHOR_SETTLE_INTERVAL_MS)
        },
        [virtualizer, noteProgrammaticScroll]
    )

    // The open's top-or-bottom verdict, re-taken once real measurements exist. The opening commit only
    // has estimates for the rows under the anchor (they render and measure a few frames later), and the
    // estimates habitually undershoot real markdown — deciding from them alone opens threads with a
    // viewport of response at the bottom instead of on the question. So the open lands on the anchor
    // provisionally (the scroll clamps to the bottom by itself when content is truly short) and this
    // loop settles the verdict: enough content measured below ⇒ the anchor stands; the window ending
    // still short — or the live stream appending before it ends, which makes the open a live-edge open —
    // ⇒ a bottom open, pinned. Stops the moment the reader scrolls: their position, their call.
    const scheduleOpenDecision = useCallback(
        (anchorIndex: number): void => {
            const startedAt = performance.now()
            const itemsAtOpen = itemsLengthRef.current
            let remaining = ANCHOR_SETTLE_CHECKS
            const commitBottomOpen = (el: HTMLElement): void => {
                el.scrollTop = el.scrollHeight
                noteProgrammaticScroll()
                setPinned(true)
            }
            const tick = (): void => {
                const el = scrollRef.current
                if (!el || lastUserScrollAtRef.current > startedAt || pinnedRef.current) {
                    return
                }
                const viewport = el.clientHeight
                const totalSize = virtualizer.getTotalSize()
                const anchorStart = virtualizer.measurementsCache[anchorIndex]?.start
                const contentBelow = anchorStart !== undefined ? totalSize - anchorStart : 0
                if (viewport > 0 && contentBelow >= viewport) {
                    return
                }
                if (itemsLengthRef.current !== itemsAtOpen) {
                    commitBottomOpen(el)
                    return
                }
                remaining -= 1
                if (remaining > 0) {
                    setTimeout(tick, ANCHOR_SETTLE_INTERVAL_MS)
                    return
                }
                commitBottomOpen(el)
            }
            setTimeout(tick, ANCHOR_SETTLE_INTERVAL_MS)
        },
        [virtualizer, noteProgrammaticScroll, setPinned]
    )

    // Initial open (once): land before the browser paints, so a long thread never shows a top-frame
    // flicker or a visible crawl. A thread that already has messages opens on its last meaningful turn —
    // the anchor row (the last human message) at the top of the viewport, its response below — whether or
    // not the agent is still working on it: a reader arriving mid-turn wants the question that was asked,
    // not the tail of the answer to it. That is only possible when at least a viewport of content follows
    // the anchor; with less, the scroll clamps and the open is a plain bottom open — no padding is ever
    // reserved to force the anchor higher, the message just sits wherever the content puts it. No anchor
    // ⇒ bottom open too.
    //
    // Whether the landing starts pinned follows from its kind: an anchor at the top is a reading
    // position, so it unpins and streaming must not steal it; a bottom open pins, following from the
    // first frame whenever a turn is live.
    // Waits for the items to finish assembling, not merely for one to exist: the run-context header and
    // the thinking footer can commit before any message does, and with debug rows enabled the history
    // replay's earliest fold commits carry renderable console items long before the human turns land.
    // Spending the once-only open on such a commit finds no anchor and opens the thread at the bottom.
    useLayoutEffect(() => {
        if (!virtualized || !stickToBottom || didInitialScrollRef.current || itemsLoading || items.length === 0) {
            return
        }
        didInitialScrollRef.current = true
        const anchorIndex = anchorItemKey != null ? findVirtualIndexForKey(anchorItemKey) : -1
        const el = scrollRef.current
        if (anchorIndex >= 0) {
            // Provisional anchor landing — this commit only has estimates for the rows under the anchor,
            // so whether the thread is really "top" or "bottom" shaped is decided by the decision loop
            // once measurements land (see `scheduleOpenDecision`). The scroll itself is safe under
            // either truth: a genuinely short thread clamps to the bottom on its own. The reconciler
            // this arms re-targets a *stable* offset — rows above the anchor don't move when the tail
            // grows — so it settles in a frame or two; the settle loop then covers the drift the
            // reconciler can't (see `scheduleAnchorSettle`).
            virtualizer.scrollToIndex(anchorIndex, { align: 'start' })
            noteProgrammaticScroll()
            setPinned(false)
            bottomRepinBlockedUntilRef.current = performance.now() + BOTTOM_REPIN_BLOCK_MS
            scheduleAnchorSettle(anchorIndex)
            scheduleOpenDecision(anchorIndex)
            return
        }
        if (turnActive && el) {
            // Deliberately not `scrollToIndex` for a thread that is already streaming: that arms the
            // core's reconciler against a target that never stabilizes — it recomputes the growing end
            // every frame for up to five seconds, with no notion of a user gesture cancelling it, so
            // every upward scroll the reader attempts in that window is undone. The follow effect below
            // owns the landing instead: it holds the bottom as rows measure and yields the moment the
            // reader scrolls away.
            el.scrollTop = el.scrollHeight
        } else {
            // Settled thread: nothing is growing, so the reconciler's target stabilizes within a frame
            // or two, and it is the accurate way to land on the last row's end while rows are
            // unmeasured.
            virtualizer.scrollToIndex(rowCount - 1, { align: 'end' })
        }
        noteProgrammaticScroll()
        setPinned(true)
    }, [
        virtualized,
        stickToBottom,
        rowCount,
        virtualizer,
        turnActive,
        anchorItemKey,
        itemsLoading,
        findVirtualIndexForKey,
        noteProgrammaticScroll,
        setPinned,
        scheduleAnchorSettle,
        scheduleOpenDecision,
        items.length,
    ])

    // Anchor-on-change (see `anchorItemKey`): a key change means a new anchor row landed. An anchor the
    // thread has never held before is a fresh send — pin to the bottom and follow the answer from there;
    // the sent message rides up naturally as the response streams in. An anchor whose key already
    // existed (a replayed turn) just scrolls to it. Novelty, not position: the fold inserts a sent
    // message at the *turn start*, behind any debug/status rows the turn already carries, so on a send
    // the anchor is frequently not the trailing item and any is-it-last test classifies the send by
    // whichever frames happened to land first. The first populated commit only adopts the key: the
    // initial-open effect above owns that scroll.
    // Gated on `itemsLoading` like the initial open — adopting mid-replay would pin the pre-history
    // anchor value (typically null) and misread the full history's anchor as a fresh send.
    useLayoutEffect(() => {
        if (!virtualized || itemsLoading || items.length === 0) {
            return
        }
        const prevKeys = prevItemKeysRef.current
        prevItemKeysRef.current = new Set(items.map((item, index) => getItemKey(item, index)))
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
        const isFreshSend = prevKeys === null || !prevKeys.has(anchorItemKey)
        if (!isFreshSend) {
            virtualizer.scrollToIndex(anchorIndex, { align: 'start' })
            noteProgrammaticScroll()
            // Same estimate-clamp settle as the initial open: the landing may touch the bottom
            // transiently, and those touches must not read as the reader arriving there.
            bottomRepinBlockedUntilRef.current = performance.now() + BOTTOM_REPIN_BLOCK_MS
            scheduleAnchorSettle(anchorIndex)
            return
        }
        // Sending is an explicit request to follow the answer, wherever the reader had scrolled to
        // while composing — pin and land on the bottom now rather than leaving it to the reader; the
        // follow effect keeps it there as the turn streams.
        setPinned(true)
        const el = scrollRef.current
        if (el) {
            el.scrollTop = el.scrollHeight
            noteProgrammaticScroll()
        }
    }, [
        virtualized,
        items,
        getItemKey,
        anchorItemKey,
        itemsLoading,
        findVirtualIndexForKey,
        virtualizer,
        setPinned,
        noteProgrammaticScroll,
        scheduleAnchorSettle,
    ])

    // Pin/unpin from what the reader did, not from where they ended up. Movement that the scroll range
    // itself doesn't explain is the reader; everything else is content shifting under them. Asymmetric on
    // purpose: leaving takes the smallest upward movement, because a gesture the view fights is the whole
    // complaint, while returning takes an actual arrival at the bottom, because anything looser re-arms
    // the follow while the reader is still reading a few lines up.
    //
    // The wheel and touch listeners catch the *first* frame — they fire before the scroll they cause, and
    // they register even when the offset can't move (already at the top, or the frame's growth cancels the
    // gesture out). The scroll listener catches everything without a gesture event: scrollbar drags,
    // PageUp, momentum.
    useEffect(() => {
        const el = scrollRef.current
        if (!virtualized || !stickToBottom || !el) {
            return
        }
        peakTopRef.current = el.scrollTop
        let touchStartY: number | null = null
        let touchStartX: number | null = null
        const onWheel = (event: WheelEvent): void => {
            if (event.deltaY !== 0) {
                lastUserScrollAtRef.current = performance.now()
            }
            if (event.deltaY < 0) {
                setPinned(false)
            } else if (event.deltaY > 0) {
                // An explicit downward gesture is unambiguous — the reader heading for the bottom must
                // not be told "not yet" by the post-landing block.
                bottomRepinBlockedUntilRef.current = 0
            }
        }
        const onTouchStart = (event: TouchEvent): void => {
            const touch = event.touches[0]
            touchStartY = touch?.clientY ?? null
            touchStartX = touch?.clientX ?? null
        }
        // A finger moving *down* scrolls the content up. Vertical dominance is required so a horizontal
        // swipe across a wide tool card or code block doesn't read as leaving the bottom.
        const onTouchMove = (event: TouchEvent): void => {
            const touch = event.touches[0]
            if (!touch || touchStartY === null || touchStartX === null) {
                return
            }
            const deltaY = touch.clientY - touchStartY
            if (Math.abs(deltaY) > Math.abs(touch.clientX - touchStartX)) {
                lastUserScrollAtRef.current = performance.now()
                if (deltaY > 0) {
                    setPinned(false)
                } else if (deltaY < 0) {
                    // Finger moving up scrolls the content down — the same explicit "heading for the
                    // bottom" signal as a downward wheel, so it clears the post-landing block too.
                    bottomRepinBlockedUntilRef.current = 0
                }
            }
        }
        const onScroll = (): void => {
            const top = el.scrollTop
            const maxTop = Math.max(0, el.scrollHeight - el.clientHeight)
            // Content shrinking under the reader — a tool card's accordion collapsing the moment the tool
            // completes, which on this surface is every finished tool — lowers the scroll range, and the
            // browser clamps `scrollTop` down with it. That
            // is an offset decrease nobody asked for, and reading it as a gesture would unpin the thread
            // mid-turn every time a tool finished. A clamp can never pull below the new maximum, so the
            // maximum is the line between "the content moved" and "the reader moved". Growth needs no
            // such correction: it moves `scrollHeight`, never `scrollTop`.
            peakTopRef.current = Math.min(peakTopRef.current, maxTop)
            // An event that lands where software recently wrote is a write echoing back, not the reader
            // (see `programmaticScrollsRef`) — adopt the position and decide nothing from it. A reader
            // gesture racing this window still lands on a different offset (or came in as a wheel/touch
            // event, which unpins before any scroll event fires).
            const now = performance.now()
            const writes = programmaticScrollsRef.current
            while (writes.length > 0 && now - writes[0].at >= PROGRAMMATIC_SCROLL_MATCH_MS) {
                writes.shift()
            }
            const prevEventTop = lastScrollEventTopRef.current
            lastScrollEventTopRef.current = top
            if (writes.some((write) => Math.abs(top - Math.min(Math.max(0, write.value), maxTop)) <= UNPIN_SLACK)) {
                peakTopRef.current = top
                return
            }
            // A downward move that lands exactly on the (new) maximum is the shrink clamp again — no
            // write explains it because the browser performed it, and counting it as the reader would
            // cancel a settle loop the moment a tool card above collapses.
            const isShrinkClamp = prevEventTop !== null && top < prevEventTop && top >= maxTop - UNPIN_SLACK
            if (!isShrinkClamp) {
                lastUserScrollAtRef.current = performance.now()
            }
            if (pinnedRef.current) {
                if (top < peakTopRef.current - UNPIN_SLACK) {
                    setPinned(false)
                } else {
                    peakTopRef.current = Math.max(peakTopRef.current, top)
                }
                return
            }
            if (
                followingRef.current &&
                maxTop - top <= AT_BOTTOM_EPSILON &&
                performance.now() >= bottomRepinBlockedUntilRef.current
            ) {
                setPinned(true)
            }
        }
        el.addEventListener('wheel', onWheel, { passive: true })
        el.addEventListener('touchstart', onTouchStart, { passive: true })
        el.addEventListener('touchmove', onTouchMove, { passive: true })
        el.addEventListener('scroll', onScroll, { passive: true })
        return () => {
            el.removeEventListener('wheel', onWheel)
            el.removeEventListener('touchstart', onTouchStart)
            el.removeEventListener('touchmove', onTouchMove)
            el.removeEventListener('scroll', onScroll)
        }
        // Deliberately not keyed on the pinned state: re-subscribing mid-gesture would reset the peak
        // baseline, which is the one thing that has to survive a gesture.
    }, [virtualized, stickToBottom, setPinned])

    // The turn's tail arrives after the turn is over — usage and cost come on their own stream frames and
    // the footer swaps to them a commit or two later — so following has to outlast `turnActive` by a beat
    // or that last row renders just below the fold. Timed rather than keyed on the content itself: what
    // lands after a turn ends is open-ended, and the grace costs nothing because an upward gesture unpins
    // through it just the same.
    useEffect(() => {
        const wasActive = prevTurnActiveRef.current
        prevTurnActiveRef.current = turnActive
        if (turnActive || !wasActive) {
            setFollowGrace(false)
            return
        }
        setFollowGrace(true)
        const timeout = setTimeout(() => setFollowGrace(false), FOLLOW_GRACE_MS)
        return () => clearTimeout(timeout)
    }, [turnActive])

    // Runs every commit: while a turn is live (or just ended, see above) and the reader is pinned, keep
    // the bottom in view. Each streamed frame is a commit, so this needs no other trigger; the core's
    // at-end resize compensation smooths growth that lands between commits. Writes `scrollTop` directly
    // instead of `scrollToEnd()`: the latter arms the core's multi-frame scroll reconciler, which
    // re-targets the (growing) end every frame and overrides the user's attempt to scroll away —
    // exactly the gesture that must win here.
    useLayoutEffect(() => {
        // Inert while items are still assembling: following a partial fold would walk the scroll to the
        // bottom of a thread whose open — which owns the landing — hasn't happened yet.
        if (!virtualized || !stickToBottom || itemsLoading || !following || !pinnedRef.current) {
            return
        }
        const el = scrollRef.current
        if (el && el.scrollHeight - el.scrollTop - el.clientHeight > AT_BOTTOM_EPSILON) {
            el.scrollTop = el.scrollHeight
            noteProgrammaticScroll()
        }
    })

    // Mobile Safari: the soft keyboard shrinks the visual (not layout) viewport, so a pinned bottom can slip
    // behind it. Re-assert on visualViewport changes — for a reader who is actually pinned; a proximity
    // check here would be the last place a bottom band could yank back someone who scrolled away.
    useEffect(() => {
        if (!virtualized || !stickToBottom || typeof window === 'undefined' || !window.visualViewport) {
            return
        }
        const viewport = window.visualViewport
        const onViewportChange = (): void => {
            if (!pinnedRef.current) {
                return
            }
            // By hand, not `scrollToEnd()`, for the same reason the follow effect writes `scrollTop`
            // itself: that call arms the core's multi-frame reconciler, which the reader cannot interrupt.
            requestAnimationFrame(() => {
                const el = scrollRef.current
                if (el && el.scrollHeight - el.scrollTop - el.clientHeight > AT_BOTTOM_EPSILON) {
                    el.scrollTop = el.scrollHeight
                    noteProgrammaticScroll()
                }
            })
        }
        viewport.addEventListener('resize', onViewportChange)
        viewport.addEventListener('scroll', onViewportChange)
        return () => {
            viewport.removeEventListener('resize', onViewportChange)
            viewport.removeEventListener('scroll', onViewportChange)
        }
    }, [virtualized, stickToBottom, noteProgrammaticScroll])

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
                {/*
                 * `overflow-anchor: none` because the virtualizer already owns every row's position and
                 * compensates content growth itself. Chrome's native scroll anchoring would compensate the
                 * same growth a second time — the rows are absolutely positioned inside the scroller, so
                 * they are anchor candidates, not excluded — and two independent corrections for one
                 * resize is a shake by construction.
                 */}
                <div
                    ref={scrollRef}
                    className={cn(
                        'flex-1 min-h-0 overflow-y-auto overflow-x-hidden overscroll-contain [overflow-anchor:none]',
                        listClassName
                    )}
                >
                    {/* Height is written imperatively by the virtualizer (`containerRef` + `directDomUpdates`). */}
                    <div ref={virtualizer.containerRef} style={{ position: 'relative', width: '100%' }}>
                        {virtualizer.getVirtualItems().map((vi) => (
                            <InternalRow key={String(vi.key)} index={vi.index} renderRow={renderRow} />
                        ))}
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
