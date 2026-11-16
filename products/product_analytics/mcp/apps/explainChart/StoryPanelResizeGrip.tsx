import { type KeyboardEvent, type PointerEvent, type ReactElement, useRef } from 'react'

import { ResizeGrip } from '@posthog/quill'

const KEYBOARD_STEP = 16

export interface StoryPanelResizeGripProps {
    getWidth: () => number
    minWidth: number
    maxWidth: number
    onResize: (width: number) => void
    onReset: () => void
}

/** The drag handle on the panel's start edge. Dragging toward the chart widens the panel. */
export function StoryPanelResizeGrip({
    getWidth,
    minWidth,
    maxWidth,
    onResize,
    onReset,
}: StoryPanelResizeGripProps): ReactElement {
    const drag = useRef<{ x: number; width: number } | null>(null)

    const onPointerDown = (event: PointerEvent<HTMLDivElement>): void => {
        if (event.button !== 0) {
            return
        }
        event.preventDefault()
        event.currentTarget.setPointerCapture(event.pointerId)
        drag.current = { x: event.clientX, width: getWidth() }
    }

    const onPointerMove = (event: PointerEvent<HTMLDivElement>): void => {
        if (drag.current) {
            onResize(drag.current.width + drag.current.x - event.clientX)
        }
    }

    const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            event.preventDefault()
            onResize(getWidth() + (event.key === 'ArrowLeft' ? KEYBOARD_STEP : -KEYBOARD_STEP))
        }
    }

    return (
        <ResizeGrip
            aria-label="Resize the explanation"
            aria-valuenow={Math.round(getWidth())}
            aria-valuemin={minWidth}
            aria-valuemax={Number.isFinite(maxWidth) ? Math.round(maxWidth) : undefined}
            tabIndex={0}
            // The panel's border is the line, so only the pill shows, centered on that border.
            className="absolute inset-y-0 start-0 z-10 hidden -translate-x-1/2 bg-transparent [--quill-resizable-hit-size:0.5rem] @3xl/story:flex rtl:translate-x-1/2"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={() => (drag.current = null)}
            onPointerCancel={() => (drag.current = null)}
            onKeyDown={onKeyDown}
            onDoubleClick={onReset}
            data-attr="explain-chart-panel-resize"
        />
    )
}
