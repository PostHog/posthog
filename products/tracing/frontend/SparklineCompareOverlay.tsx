import { useEffect, useLayoutEffect, useRef, useState } from 'react'

interface Window {
    startMs: number
    endMs: number
}

interface SparklineCompareOverlayProps {
    /** Full visible time window the sparkline covers, in ms — used for pixel mapping and clamping. */
    fullStartMs: number
    fullEndMs: number
    currentWindow: Window
    previousWindow: Window
    /** Fires on mouseup with the final positions of both windows. */
    onChange: (current: Window, previous: Window) => void
}

type DragKind = 'current-body' | 'previous-body' | 'current-left' | 'current-right' | 'previous-left' | 'previous-right'

interface DragState {
    kind: DragKind
    startX: number
    initialCurrent: Window
    initialPrevious: Window
}

// Shared with the ComparisonBar pills so "Current"/"Baseline" reads the same everywhere.
export const COMPARE_CURRENT_COLOR = 'rgba(255, 165, 0, 0.25)' // light orange
export const COMPARE_CURRENT_BORDER = 'rgba(255, 140, 0, 0.85)'
export const COMPARE_PREVIOUS_COLOR = 'rgba(99, 179, 237, 0.25)' // light blue
export const COMPARE_PREVIOUS_BORDER = 'rgba(56, 145, 212, 0.85)'

const EDGE_WIDTH_PX = 6
const BORDER_WIDTH_PX = 2
const MIN_DURATION_MS = 60_000

function clampWindowToBounds(w: Window, fullStartMs: number, fullEndMs: number): Window {
    let { startMs, endMs } = w
    const duration = endMs - startMs
    if (startMs < fullStartMs) {
        startMs = fullStartMs
        endMs = startMs + duration
    }
    if (endMs > fullEndMs) {
        endMs = fullEndMs
        startMs = endMs - duration
    }
    return { startMs, endMs }
}

export function SparklineCompareOverlay({
    fullStartMs,
    fullEndMs,
    currentWindow,
    previousWindow,
    onChange,
}: SparklineCompareOverlayProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const [width, setWidth] = useState(0)
    const [drag, setDrag] = useState<DragState | null>(null)
    // In-flight preview during drag; committed via onChange on mouseup.
    const [previewCurrent, setPreviewCurrent] = useState<Window | null>(null)
    const [previewPrevious, setPreviewPrevious] = useState<Window | null>(null)

    useLayoutEffect(() => {
        if (!containerRef.current) {
            return
        }
        const el = containerRef.current
        setWidth(el.clientWidth)
        const observer = new ResizeObserver((entries) => {
            for (const entry of entries) {
                setWidth(entry.contentRect.width)
            }
        })
        observer.observe(el)
        return () => observer.disconnect()
    }, [])

    const totalMs = fullEndMs - fullStartMs
    const pxPerMs = totalMs > 0 && width > 0 ? width / totalMs : 0
    const msPerPx = pxPerMs > 0 ? 1 / pxPerMs : 0

    const effectiveCurrent = previewCurrent ?? currentWindow
    const effectivePrevious = previewPrevious ?? previousWindow

    function msToPx(ms: number): number {
        return (ms - fullStartMs) * pxPerMs
    }

    function applyDrag(kind: DragKind, dxMs: number, initialCurrent: Window, initialPrevious: Window): void {
        const initialDuration = initialCurrent.endMs - initialCurrent.startMs

        if (kind === 'current-body') {
            const startMs = initialCurrent.startMs + dxMs
            const moved = clampWindowToBounds({ startMs, endMs: startMs + initialDuration }, fullStartMs, fullEndMs)
            setPreviewCurrent(moved)
            return
        }
        if (kind === 'previous-body') {
            const startMs = initialPrevious.startMs + dxMs
            const moved = clampWindowToBounds({ startMs, endMs: startMs + initialDuration }, fullStartMs, fullEndMs)
            setPreviewPrevious(moved)
            return
        }

        // Edge drag: the dragged edge tracks the cursor. The opposite edge of the same window
        // stays put. Duration is shared, so the OTHER window keeps its startMs and adopts
        // the new duration.
        let draggedStart = 0
        let draggedEnd = 0
        let draggedIsCurrent = false

        if (kind === 'current-left') {
            draggedStart = initialCurrent.startMs + dxMs
            draggedEnd = initialCurrent.endMs
            draggedIsCurrent = true
        } else if (kind === 'current-right') {
            draggedStart = initialCurrent.startMs
            draggedEnd = initialCurrent.endMs + dxMs
            draggedIsCurrent = true
        } else if (kind === 'previous-left') {
            draggedStart = initialPrevious.startMs + dxMs
            draggedEnd = initialPrevious.endMs
        } else if (kind === 'previous-right') {
            draggedStart = initialPrevious.startMs
            draggedEnd = initialPrevious.endMs + dxMs
        }

        // Clamp dragged edge to sparkline bounds.
        draggedStart = Math.max(fullStartMs, draggedStart)
        draggedEnd = Math.min(fullEndMs, draggedEnd)
        if (draggedEnd - draggedStart < MIN_DURATION_MS) {
            return
        }

        const newDuration = draggedEnd - draggedStart
        if (draggedIsCurrent) {
            setPreviewCurrent({ startMs: draggedStart, endMs: draggedEnd })
            const followerStart = initialPrevious.startMs
            const follower = clampWindowToBounds(
                { startMs: followerStart, endMs: followerStart + newDuration },
                fullStartMs,
                fullEndMs
            )
            setPreviewPrevious(follower)
        } else {
            setPreviewPrevious({ startMs: draggedStart, endMs: draggedEnd })
            const followerStart = initialCurrent.startMs
            const follower = clampWindowToBounds(
                { startMs: followerStart, endMs: followerStart + newDuration },
                fullStartMs,
                fullEndMs
            )
            setPreviewCurrent(follower)
        }
    }

    useEffect(() => {
        if (!drag) {
            return
        }
        const onMove = (e: MouseEvent): void => {
            const dxPx = e.clientX - drag.startX
            const dxMs = dxPx * msPerPx
            applyDrag(drag.kind, dxMs, drag.initialCurrent, drag.initialPrevious)
        }
        const onUp = (): void => {
            const finalCurrent = previewCurrent ?? drag.initialCurrent
            const finalPrevious = previewPrevious ?? drag.initialPrevious
            setDrag(null)
            setPreviewCurrent(null)
            setPreviewPrevious(null)
            // Only fire onChange if something actually moved.
            const moved =
                finalCurrent.startMs !== drag.initialCurrent.startMs ||
                finalCurrent.endMs !== drag.initialCurrent.endMs ||
                finalPrevious.startMs !== drag.initialPrevious.startMs ||
                finalPrevious.endMs !== drag.initialPrevious.endMs
            if (moved) {
                onChange(finalCurrent, finalPrevious)
            }
        }
        window.addEventListener('mousemove', onMove)
        window.addEventListener('mouseup', onUp)
        return () => {
            window.removeEventListener('mousemove', onMove)
            window.removeEventListener('mouseup', onUp)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [drag, msPerPx, previewCurrent, previewPrevious])

    function beginDrag(kind: DragKind, e: React.MouseEvent): void {
        e.preventDefault()
        e.stopPropagation()
        setDrag({
            kind,
            startX: e.clientX,
            initialCurrent: currentWindow,
            initialPrevious: previousWindow,
        })
    }

    function renderWindow(
        window: Window,
        kind: 'current' | 'previous',
        fill: string,
        border: string,
        label: string
    ): JSX.Element | null {
        if (pxPerMs === 0) {
            return null
        }
        const left = msToPx(window.startMs)
        const right = msToPx(window.endMs)
        const w = Math.max(2, right - left)
        return (
            <div
                className="absolute top-0 h-full"
                style={{
                    left,
                    width: w,
                    backgroundColor: fill,
                    borderLeft: `${BORDER_WIDTH_PX}px solid ${border}`,
                    borderRight: `${BORDER_WIDTH_PX}px solid ${border}`,
                    pointerEvents: 'auto',
                    cursor: 'grab',
                }}
                onMouseDown={(e) => beginDrag(`${kind}-body` as DragKind, e)}
                title={`${label} window — drag to move, drag an edge to resize`}
            >
                {/* Persistent label chip: the drag affordance is invisible without it. */}
                <span
                    className="absolute top-0 left-0 px-1 text-[10px] font-semibold text-white leading-4 whitespace-nowrap pointer-events-none select-none rounded-br"
                    style={{ backgroundColor: border }}
                >
                    {label}
                </span>
                <div
                    className="absolute top-0 h-full"
                    style={{
                        left: -EDGE_WIDTH_PX / 2 - BORDER_WIDTH_PX / 2,
                        width: EDGE_WIDTH_PX,
                        cursor: 'ew-resize',
                    }}
                    onMouseDown={(e) => beginDrag(`${kind}-left` as DragKind, e)}
                />
                <div
                    className="absolute top-0 h-full"
                    style={{
                        right: -EDGE_WIDTH_PX / 2 - BORDER_WIDTH_PX / 2,
                        width: EDGE_WIDTH_PX,
                        cursor: 'ew-resize',
                    }}
                    onMouseDown={(e) => beginDrag(`${kind}-right` as DragKind, e)}
                />
            </div>
        )
    }

    return (
        <div ref={containerRef} className="absolute inset-0" style={{ pointerEvents: 'none' }}>
            {renderWindow(effectivePrevious, 'previous', COMPARE_PREVIOUS_COLOR, COMPARE_PREVIOUS_BORDER, 'Baseline')}
            {renderWindow(effectiveCurrent, 'current', COMPARE_CURRENT_COLOR, COMPARE_CURRENT_BORDER, 'Current')}
        </div>
    )
}
