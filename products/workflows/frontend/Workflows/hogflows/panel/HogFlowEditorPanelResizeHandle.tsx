import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'

const MIN_PANEL_WIDTH = 400
const MAX_PANEL_WIDTH = 800

export interface HogFlowEditorPanelResizeHandleProps {
    width: number
    onResize: (width: number) => void
    onReset: () => void
}

export function HogFlowEditorPanelResizeHandle({
    width,
    onResize,
    onReset,
}: HogFlowEditorPanelResizeHandleProps): JSX.Element {
    const startX = useRef(0)
    const startWidth = useRef(width)
    const handleRef = useRef<HTMLButtonElement>(null)
    const [maxWidth, setMaxWidth] = useState(MAX_PANEL_WIDTH)

    const minWidth = Math.min(MIN_PANEL_WIDTH, maxWidth)
    const clampWidth = (nextWidth: number, widthLimit = maxWidth): number =>
        Math.min(Math.max(nextWidth, Math.min(MIN_PANEL_WIDTH, widthLimit)), widthLimit)
    const visibleWidth = clampWidth(width)

    useEffect(() => {
        const container = handleRef.current?.parentElement?.parentElement
        if (!container) {
            return
        }

        const updateMaxWidth = (): void =>
            setMaxWidth(Math.min(MAX_PANEL_WIDTH, container.getBoundingClientRect().width))
        const observer = new ResizeObserver(updateMaxWidth)
        updateMaxWidth()
        observer.observe(container)
        return () => observer.disconnect()
    }, [])

    const startResize = (event: ReactPointerEvent<HTMLButtonElement>): void => {
        if (event.button !== 0) {
            return
        }

        event.preventDefault()
        event.stopPropagation()
        startX.current = event.clientX
        const widthLimit = Math.min(
            MAX_PANEL_WIDTH,
            event.currentTarget.parentElement?.parentElement?.getBoundingClientRect().width ?? MAX_PANEL_WIDTH
        )
        setMaxWidth(widthLimit)
        startWidth.current = clampWidth(width, widthLimit)
        event.currentTarget.setPointerCapture(event.pointerId)
    }

    const resize = (event: ReactPointerEvent<HTMLButtonElement>): void => {
        if (!event.currentTarget.hasPointerCapture(event.pointerId)) {
            return
        }

        onResize(clampWidth(startWidth.current + startX.current - event.clientX))
    }

    return (
        <button
            type="button"
            aria-label="Resize workflow editor panel"
            aria-orientation="vertical"
            ref={handleRef}
            aria-valuenow={visibleWidth}
            aria-valuemin={minWidth}
            aria-valuemax={maxWidth}
            className="group absolute top-4 bottom-4 left-0 z-20 w-3 cursor-ew-resize border-0 bg-transparent p-0 opacity-0 transition-opacity hover:opacity-100 focus-visible:opacity-100"
            onPointerDown={startResize}
            onPointerMove={resize}
            onDoubleClick={onReset}
            onKeyDown={(event) => {
                if (event.key === 'ArrowLeft') {
                    event.preventDefault()
                    onResize(clampWidth(visibleWidth + 10))
                } else if (event.key === 'ArrowRight') {
                    event.preventDefault()
                    onResize(clampWidth(visibleWidth - 10))
                } else if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onReset()
                }
            }}
            data-attr="workflow-editor-panel-resize-handle"
        >
            <span className="absolute inset-y-0 left-2 w-px bg-border-primary opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100" />
        </button>
    )
}
