import { PointerEvent as ReactPointerEvent } from 'react'

import { MIN_COLUMN_WIDTH } from './columnWidths'

export interface ColumnResizeHandleProps {
    /** Column heading, so the handle has an accessible name of its own. */
    columnLabel: string
    width: number
    onResizeStart: (event: ReactPointerEvent) => void
    onNudge: (direction: -1 | 1) => void
    onReset: () => void
}

/** Grab bar on the right edge of a header cell. Drag, arrow keys, or double-click to reset. */
export function ColumnResizeHandle({
    columnLabel,
    width,
    onResizeStart,
    onNudge,
    onReset,
}: ColumnResizeHandleProps): JSX.Element {
    return (
        <div
            role="separator"
            aria-orientation="vertical"
            aria-label={`Resize ${columnLabel} column`}
            aria-valuenow={width}
            aria-valuemin={MIN_COLUMN_WIDTH}
            tabIndex={0}
            // The divider stays visible so the column reads as resizable without hovering it first.
            className="group absolute inset-y-0 -right-1 z-1 flex w-2 justify-center cursor-col-resize"
            onPointerDown={onResizeStart}
            onDoubleClick={onReset}
            onKeyDown={(event) => {
                if (event.key === 'ArrowLeft') {
                    event.preventDefault()
                    onNudge(-1)
                } else if (event.key === 'ArrowRight') {
                    event.preventDefault()
                    onNudge(1)
                } else if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onReset()
                }
            }}
            data-attr="tracing-column-resize-handle"
        >
            <div className="h-full w-px bg-border group-hover:w-0.5 group-hover:bg-accent group-focus-visible:w-0.5 group-focus-visible:bg-accent" />
        </div>
    )
}
