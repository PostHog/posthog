/**
 * `<FloatingDockPanel />` — fixed-position shell for the chat dock,
 * used when the user picks the "floating" layout mode.
 *
 *   - Drag by the **header area** (any descendant carrying
 *     `data-dock-drag-handle`) to move the panel around the viewport.
 *     Buttons inside the header still receive clicks.
 *   - **Snap targets** when dropped near a screen edge:
 *       - close to a single vertical edge → `left` / `right` full-height strip
 *       - close to a corner (both axes) → corner snap, panel keeps its
 *         natural width and height, hugs the corner with `FLOAT_MARGIN` gap
 *     Top/bottom edge snap (full-width horizontal strip) is deliberately
 *     not supported — the drag handle would be inside the strip.
 *   - **Float margin** — every state (snapped and free-floating) keeps a
 *     `FLOAT_MARGIN` gap from the viewport edges so the panel always reads
 *     as a floating window.
 *   - **Resize handles** at the corners (NE / NW / SE / SW) when
 *     free-floating or corner-snapped (only the inner corner is shown
 *     when corner-snapped — the other three would move the panel away
 *     from the snap point). For edge snaps (`left` / `right`) only the
 *     opposite edge handle (e.g. east when snapped left) is shown.
 *
 * Geometry is owned by `useDockLayout`; this component is mostly DOM +
 * mouse-listener wiring. The dock content lives in `children`.
 */

'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { DockSnap, FloatingGeometry, UseDockLayout } from '@/lib/useDockLayout'

/** Min/max constraints so the panel can't be dragged off-screen or sized into nothing. */
const MIN_W = 320
const MIN_H = 320
const MAX_W = 900
const MAX_H = 1080

/** How close (in px) the panel has to be to a vertical edge to snap on release. */
const SNAP_PX = 80

/** Minimum gap between a free-floating panel and the viewport edges. */
const FLOAT_MARGIN = 16

interface FloatingDockPanelProps {
    floating: FloatingGeometry
    setFloating: UseDockLayout['setFloating']
    children: React.ReactNode
}

interface DragState {
    /** Pointer position when the gesture started. */
    startX: number
    startY: number
    /** Panel position when the gesture started. */
    originX: number
    originY: number
    /** Width/height captured at gesture start (only used for resize). */
    originW: number
    originH: number
    /** Which gesture is active. */
    kind: 'move' | 'resize'
    /** Which corner is being dragged (for `kind === 'resize'`). */
    handle?: ResizeHandle
}

type ResizeHandle = 'nw' | 'ne' | 'sw' | 'se' | 'n' | 's' | 'e' | 'w'

export function FloatingDockPanel({ floating, setFloating, children }: FloatingDockPanelProps): React.ReactElement {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const dragRef = useRef<DragState | null>(null)
    // Local `dragging` flag drives visual feedback (cursor, snap preview) and
    // disables transition during a drag so the panel tracks the pointer 1:1.
    const [dragging, setDragging] = useState<DragState['kind'] | null>(null)
    const [snapPreview, setSnapPreview] = useState<DockSnap>(null)

    // Re-render on viewport resize so corner / edge snaps stay anchored
    // to their corner. `resolveRect` already computes positions relative
    // to the live `window.innerWidth/Height`, but without a viewport
    // dep the memo would never recompute on resize and the panel would
    // drift away from its corner.
    const viewport = useViewportSize()
    const resolved = useMemo(() => resolveRect(floating), [floating, viewport.w, viewport.h])

    /* ── Move (drag header) ─────────────────────────────────────── */
    //
    // The chat dock is rendered into a slot inside this panel via
    // `createPortal()` (see AppShell). React's synthetic event
    // bubbling walks the *virtual* tree, not the DOM — and the
    // portal's React parent is the AppShell, not this component. So
    // an `onMouseDown` prop on the container div would NEVER fire for
    // mousedowns inside the portaled dock, even though the dock's
    // DOM lives inside the container. Native DOM listeners follow
    // the actual DOM tree, so we attach one in the effect below.

    useEffect(() => {
        const node = containerRef.current
        if (!node) {
            return
        }
        const handler = (e: MouseEvent): void => {
            if (!(e.target instanceof Element)) {
                return
            }
            // Only react to mousedowns that landed on the chrome row the
            // host opted in to via `data-dock-drag-handle`.
            if (!e.target.closest('[data-dock-drag-handle]')) {
                return
            }
            // …and not on an interactive control inside that row. Buttons,
            // links, menu triggers must keep receiving the click.
            if (
                e.target.closest(
                    'button, a, input, textarea, [role="menu"], [role="menuitem"], [role="menuitemcheckbox"], [role="menuitemradio"]'
                )
            ) {
                return
            }
            e.preventDefault()
            // Read live geometry so "tear-off from snapped" starts from
            // where the user actually sees the panel.
            const rect = containerRef.current?.getBoundingClientRect()
            const originX = rect?.left ?? floating.x
            const originY = rect?.top ?? floating.y
            const originW = rect?.width ?? floating.w
            const originH = rect?.height ?? floating.h
            dragRef.current = {
                kind: 'move',
                startX: e.clientX,
                startY: e.clientY,
                originX,
                originY,
                originW,
                originH,
            }
            setDragging('move')
        }
        node.addEventListener('mousedown', handler)
        return () => node.removeEventListener('mousedown', handler)
    }, [floating])

    /* ── Resize (drag corner / edge) ────────────────────────────── */

    const beginResize = useCallback(
        (handle: ResizeHandle) => (e: React.MouseEvent<HTMLDivElement>) => {
            e.preventDefault()
            e.stopPropagation()
            const rect = containerRef.current?.getBoundingClientRect()
            dragRef.current = {
                kind: 'resize',
                handle,
                startX: e.clientX,
                startY: e.clientY,
                originX: rect?.left ?? floating.x,
                originY: rect?.top ?? floating.y,
                originW: rect?.width ?? floating.w,
                originH: rect?.height ?? floating.h,
            }
            setDragging('resize')
        },
        [floating]
    )

    /* ── Window-level move/up handlers (active only while dragging) ── */

    useEffect(() => {
        if (!dragging) {
            return
        }
        const onMove = (e: MouseEvent): void => {
            const drag = dragRef.current
            if (!drag) {
                return
            }
            const dx = e.clientX - drag.startX
            const dy = e.clientY - drag.startY
            const vw = window.innerWidth
            const vh = window.innerHeight

            // Viewport-aware caps: the panel can never exceed the
            // viewport minus the FLOAT_MARGIN on both sides.
            const viewportMaxW = Math.max(MIN_W, vw - FLOAT_MARGIN * 2)
            const viewportMaxH = Math.max(MIN_H, vh - FLOAT_MARGIN * 2)

            if (drag.kind === 'move') {
                // Tear-off: as soon as the pointer moves at all in a snapped
                // state we drop the snap and treat the gesture as a free move.
                // Clamp to a FLOAT_MARGIN gap from each edge so the floating
                // panel never sits flush against the viewport.
                const maxX = Math.max(FLOAT_MARGIN, vw - drag.originW - FLOAT_MARGIN)
                const maxY = Math.max(FLOAT_MARGIN, vh - drag.originH - FLOAT_MARGIN)
                const nextX = clamp(drag.originX + dx, FLOAT_MARGIN, maxX)
                const nextY = clamp(drag.originY + dy, FLOAT_MARGIN, maxY)
                setFloating((prev) => ({
                    ...prev,
                    x: nextX,
                    y: nextY,
                    w: drag.originW,
                    h: drag.originH,
                    snap: null,
                }))
                setSnapPreview(detectSnap(nextX, nextY, drag.originW, drag.originH, vw, vh))
            } else {
                // Resize: project the drag delta onto the affected sides.
                let nextX = drag.originX
                let nextY = drag.originY
                let nextW = drag.originW
                let nextH = drag.originH
                const handle = drag.handle ?? 'se'
                if (handle.includes('e')) {
                    nextW = clamp(drag.originW + dx, MIN_W, Math.min(MAX_W, viewportMaxW))
                }
                if (handle.includes('s')) {
                    nextH = clamp(drag.originH + dy, MIN_H, Math.min(MAX_H, viewportMaxH))
                }
                if (handle.includes('w')) {
                    const widthAttempt = clamp(drag.originW - dx, MIN_W, Math.min(MAX_W, viewportMaxW))
                    nextX = drag.originX + (drag.originW - widthAttempt)
                    nextW = widthAttempt
                }
                if (handle.includes('n')) {
                    const heightAttempt = clamp(drag.originH - dy, MIN_H, Math.min(MAX_H, viewportMaxH))
                    nextY = drag.originY + (drag.originH - heightAttempt)
                    nextH = heightAttempt
                }
                setFloating((prev) => ({ ...prev, x: nextX, y: nextY, w: nextW, h: nextH }))
            }
        }

        const onUp = (): void => {
            const drag = dragRef.current
            if (!drag) {
                return
            }
            if (drag.kind === 'move') {
                const vw = window.innerWidth
                const vh = window.innerHeight
                setFloating((prev) => {
                    const snap = detectSnap(prev.x, prev.y, prev.w, prev.h, vw, vh)
                    return { ...prev, snap }
                })
            }
            dragRef.current = null
            setDragging(null)
            setSnapPreview(null)
        }

        window.addEventListener('mousemove', onMove)
        window.addEventListener('mouseup', onUp)
        return () => {
            window.removeEventListener('mousemove', onMove)
            window.removeEventListener('mouseup', onUp)
        }
    }, [dragging, setFloating])

    /* ── Render ─────────────────────────────────────────────────── */

    const snap = floating.snap
    const showHandle = (h: ResizeHandle): boolean => {
        // Only show the resize handle that doesn't immediately undo the
        // snap. For edge snaps the opposite edge; for corner snaps the
        // diagonally-opposite corner; free-floating shows all 4 corners.
        switch (snap) {
            case 'left':
                return h === 'e'
            case 'right':
                return h === 'w'
            case 'top-left':
                return h === 'se'
            case 'top-right':
                return h === 'sw'
            case 'bottom-left':
                return h === 'ne'
            case 'bottom-right':
                return h === 'nw'
            case null:
            default:
                return h === 'nw' || h === 'ne' || h === 'sw' || h === 'se'
        }
    }

    // Cursor hint: any descendant carrying `data-dock-drag-handle` (the
    // chat's header row, in practice) gets a grab cursor; switches to
    // grabbing while a move is in flight. Controls inside the header
    // (buttons, dropdown triggers) override this via their own classes.
    const cursorClass =
        dragging === 'move' ? '[&_[data-dock-drag-handle]]:cursor-grabbing' : '[&_[data-dock-drag-handle]]:cursor-grab'

    return (
        <>
            {snapPreview ? <SnapPreview snap={snapPreview} w={floating.w} h={floating.h} /> : null}
            <div
                ref={containerRef}
                className={
                    'fixed z-40 flex flex-col overflow-hidden rounded-lg border border-border bg-background shadow-xl ' +
                    (dragging ? 'select-none ' : '') +
                    cursorClass
                }
                style={{
                    left: resolved.left,
                    top: resolved.top,
                    width: resolved.width,
                    height: resolved.height,
                    transition: dragging
                        ? 'none'
                        : 'left 120ms ease, top 120ms ease, width 120ms ease, height 120ms ease',
                }}
                data-slot="floating-dock"
                data-snap={snap ?? 'none'}
            >
                {/* Resize handles. Render on top of everything so they're
                 *  reachable; pointer-events: none on the parent overlay
                 *  containers if needed isn't required — each handle is
                 *  an absolutely-positioned hit zone. */}
                {showHandle('n') ? <Handle position="n" onMouseDown={beginResize('n')} /> : null}
                {showHandle('s') ? <Handle position="s" onMouseDown={beginResize('s')} /> : null}
                {showHandle('e') ? <Handle position="e" onMouseDown={beginResize('e')} /> : null}
                {showHandle('w') ? <Handle position="w" onMouseDown={beginResize('w')} /> : null}
                {showHandle('nw') ? <Handle position="nw" onMouseDown={beginResize('nw')} /> : null}
                {showHandle('ne') ? <Handle position="ne" onMouseDown={beginResize('ne')} /> : null}
                {showHandle('sw') ? <Handle position="sw" onMouseDown={beginResize('sw')} /> : null}
                {showHandle('se') ? <Handle position="se" onMouseDown={beginResize('se')} /> : null}

                <div className="flex h-full min-h-0 w-full flex-col">{children}</div>
            </div>
        </>
    )
}

/**
 * Live viewport size. Updates on window resize so consumers can
 * recompute layout-dependent values. Cheap — just one resize listener
 * that fires at most once per frame; consumers re-render when the
 * tuple they consume changes.
 */
function useViewportSize(): { w: number; h: number } {
    const [size, setSize] = useState<{ w: number; h: number }>(() =>
        typeof window === 'undefined' ? { w: 0, h: 0 } : { w: window.innerWidth, h: window.innerHeight }
    )
    useEffect(() => {
        if (typeof window === 'undefined') {
            return
        }
        const onResize = (): void => setSize({ w: window.innerWidth, h: window.innerHeight })
        window.addEventListener('resize', onResize)
        return () => window.removeEventListener('resize', onResize)
    }, [])
    return size
}

/* ── Helpers ────────────────────────────────────────────────────── */

interface Rect {
    left: number
    top: number
    width: number
    height: number
}

function resolveRect(g: FloatingGeometry): Rect {
    const vw = typeof window !== 'undefined' ? window.innerWidth : 1440
    const vh = typeof window !== 'undefined' ? window.innerHeight : 900

    // Cap stored width/height against the live viewport — the user may
    // have resized to MAX in a wider browser then shrunk the window;
    // we'd rather show a smaller panel than overflow the viewport.
    const cappedW = Math.min(g.w, Math.max(MIN_W, vw - FLOAT_MARGIN * 2))
    const cappedH = Math.min(g.h, Math.max(MIN_H, vh - FLOAT_MARGIN * 2))

    // Edge snaps stretch vertically; corner snaps keep natural height
    // (with the same viewport-aware cap). Both keep FLOAT_MARGIN gaps.
    const stripHeight = Math.max(MIN_H, vh - FLOAT_MARGIN * 2)
    const rightLeft = Math.max(FLOAT_MARGIN, vw - cappedW - FLOAT_MARGIN)
    const bottomTop = Math.max(FLOAT_MARGIN, vh - cappedH - FLOAT_MARGIN)

    switch (g.snap) {
        case 'left':
            return { left: FLOAT_MARGIN, top: FLOAT_MARGIN, width: cappedW, height: stripHeight }
        case 'right':
            return { left: rightLeft, top: FLOAT_MARGIN, width: cappedW, height: stripHeight }
        case 'top-left':
            return { left: FLOAT_MARGIN, top: FLOAT_MARGIN, width: cappedW, height: cappedH }
        case 'top-right':
            return { left: rightLeft, top: FLOAT_MARGIN, width: cappedW, height: cappedH }
        case 'bottom-left':
            return { left: FLOAT_MARGIN, top: bottomTop, width: cappedW, height: cappedH }
        case 'bottom-right':
            return { left: rightLeft, top: bottomTop, width: cappedW, height: cappedH }
        case null:
        default:
            // Belt + braces: clamp into the FLOAT_MARGIN box. The drag
            // handler already does this, but a stored x/y that was once
            // valid may have drifted out of bounds after a viewport shrink.
            return {
                left: clamp(g.x, FLOAT_MARGIN, Math.max(FLOAT_MARGIN, vw - cappedW - FLOAT_MARGIN)),
                top: clamp(g.y, FLOAT_MARGIN, Math.max(FLOAT_MARGIN, vh - cappedH - FLOAT_MARGIN)),
                width: cappedW,
                height: cappedH,
            }
    }
}

function clamp(v: number, lo: number, hi: number): number {
    return Math.max(lo, Math.min(hi, v))
}

/**
 * Decides whether the panel should snap to a viewport edge or corner.
 *
 *   - If close to BOTH a vertical and a horizontal edge → corner snap.
 *     The panel keeps its natural size and hugs the corner.
 *   - If close to just a vertical edge (left / right) → edge snap.
 *     The panel becomes a full-height strip.
 *   - Otherwise → no snap (free floating).
 *
 * Top + bottom edge snap on their own are deliberately NOT supported
 * (a full-width horizontal strip is awkward to escape from). Corners
 * are fine because the panel keeps its natural width.
 */
function detectSnap(x: number, y: number, w: number, h: number, vw: number, vh: number): DockSnap {
    const nearLeft = x <= SNAP_PX
    const nearRight = x + w >= vw - SNAP_PX
    const nearTop = y <= SNAP_PX
    const nearBottom = y + h >= vh - SNAP_PX
    if (nearTop && nearLeft) {
        return 'top-left'
    }
    if (nearTop && nearRight) {
        return 'top-right'
    }
    if (nearBottom && nearLeft) {
        return 'bottom-left'
    }
    if (nearBottom && nearRight) {
        return 'bottom-right'
    }
    if (nearLeft) {
        return 'left'
    }
    if (nearRight) {
        return 'right'
    }
    return null
}

/* ── Subviews ───────────────────────────────────────────────────── */

function Handle({
    position,
    onMouseDown,
}: {
    position: ResizeHandle
    onMouseDown: (e: React.MouseEvent<HTMLDivElement>) => void
}): React.ReactElement {
    // Hit-zone sizing — corners are slightly chunkier for grabbability;
    // edges are slim strips along their respective side.
    const positionClass: Record<ResizeHandle, string> = {
        n: 'top-0 left-3 right-3 h-1.5 cursor-ns-resize',
        s: 'bottom-0 left-3 right-3 h-1.5 cursor-ns-resize',
        e: 'right-0 top-3 bottom-3 w-1.5 cursor-ew-resize',
        w: 'left-0 top-3 bottom-3 w-1.5 cursor-ew-resize',
        nw: 'top-0 left-0 h-3 w-3 cursor-nwse-resize',
        ne: 'top-0 right-0 h-3 w-3 cursor-nesw-resize',
        sw: 'bottom-0 left-0 h-3 w-3 cursor-nesw-resize',
        se: 'bottom-0 right-0 h-3 w-3 cursor-nwse-resize',
    }
    return <div className={'absolute z-20 ' + positionClass[position]} onMouseDown={onMouseDown} aria-hidden />
}

function SnapPreview({
    snap,
    w,
    h,
}: {
    snap: Exclude<DockSnap, null>
    /** Panel dimensions in flight — used to size corner-snap previews so they match the landing rect. */
    w: number
    h: number
}): React.ReactElement {
    // Translucent overlay showing where the panel will land on release.
    // Edge snaps stretch full-height; corner snaps show a box sized to
    // the current panel so the user sees the landing rect, not a strip.
    const style: React.CSSProperties = (() => {
        switch (snap) {
            case 'left':
                return { left: FLOAT_MARGIN, top: FLOAT_MARGIN, width: w, bottom: FLOAT_MARGIN }
            case 'right':
                return { right: FLOAT_MARGIN, top: FLOAT_MARGIN, width: w, bottom: FLOAT_MARGIN }
            case 'top-left':
                return { left: FLOAT_MARGIN, top: FLOAT_MARGIN, width: w, height: h }
            case 'top-right':
                return { right: FLOAT_MARGIN, top: FLOAT_MARGIN, width: w, height: h }
            case 'bottom-left':
                return { left: FLOAT_MARGIN, bottom: FLOAT_MARGIN, width: w, height: h }
            case 'bottom-right':
                return { right: FLOAT_MARGIN, bottom: FLOAT_MARGIN, width: w, height: h }
        }
    })()
    return (
        <div
            className="pointer-events-none fixed z-30 rounded-lg border-2 border-dashed border-primary/60 bg-primary/10 transition-opacity"
            style={style}
            aria-hidden
        />
    )
}
