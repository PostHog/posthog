import { useActions, useValues } from 'kea'
import { PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from 'react'

import { tracingConfigLogic } from '../../tracingConfigLogic'
import { MIN_COLUMN_WIDTH, ResizableColumnSpec, ResolvedColumnWidths, resolveColumnWidths } from './columnWidths'

/** How far one arrow key press moves a resize handle. */
const KEYBOARD_STEP = 16

export interface ResizableColumns {
    /** Call during render with the viewport width. The growing column absorbs what is left over. */
    resolveWidths: (availableWidth: number) => ResolvedColumnWidths
    startResize: (columnKey: string, event: ReactPointerEvent) => void
    nudgeWidth: (columnKey: string, direction: -1 | 1) => void
    resetWidth: (columnKey: string) => void
}

/**
 * Drag-to-resize widths for one table, persisted per person under `tableKey`.
 *
 * Widths depend on the viewport, which only `AutoSizer` knows, so the hook hands back
 * `resolveWidths` for the render prop to call instead of returning widths directly.
 */
export function useResizableColumns(tableKey: string, specs: ResizableColumnSpec[]): ResizableColumns {
    const { columnWidths } = useValues(tracingConfigLogic)
    const { setColumnWidth, resetColumnWidth } = useActions(tracingConfigLogic)
    const stored = columnWidths[tableKey]

    // Live width while a handle is held, so the drag stays smooth and only the final width is stored.
    const [dragged, setDragged] = useState<{ columnKey: string; width: number } | null>(null)
    // Widths the last render produced. A drag starts from what is on screen, not from the default.
    const renderedWidthsRef = useRef<Record<string, number>>({})
    const stopDragRef = useRef<(() => void) | null>(null)

    useEffect(() => () => stopDragRef.current?.(), [])

    const resolveWidths = (availableWidth: number): ResolvedColumnWidths => {
        const resolved = resolveColumnWidths(specs, stored, dragged, availableWidth)
        renderedWidthsRef.current = resolved.widths
        return resolved
    }

    const startResize = useCallback(
        (columnKey: string, event: ReactPointerEvent): void => {
            event.preventDefault()
            const startX = event.clientX
            const startWidth = renderedWidthsRef.current[columnKey] ?? MIN_COLUMN_WIDTH
            const widthAt = (clientX: number): number =>
                Math.max(MIN_COLUMN_WIDTH, Math.round(startWidth + clientX - startX))

            const onMove = (moveEvent: PointerEvent): void => {
                setDragged({ columnKey, width: widthAt(moveEvent.clientX) })
            }
            const onUp = (upEvent: PointerEvent): void => {
                stopDragRef.current?.()
                setColumnWidth(tableKey, columnKey, widthAt(upEvent.clientX))
            }

            stopDragRef.current = (): void => {
                document.removeEventListener('pointermove', onMove)
                document.removeEventListener('pointerup', onUp)
                document.body.classList.remove('cursor-col-resize', 'select-none')
                stopDragRef.current = null
                setDragged(null)
            }
            document.addEventListener('pointermove', onMove)
            document.addEventListener('pointerup', onUp)
            // Hold the resize cursor and suppress text selection for the whole drag, not only while
            // the pointer stays over the handle.
            document.body.classList.add('cursor-col-resize', 'select-none')
        },
        [setColumnWidth, tableKey]
    )

    const nudgeWidth = useCallback(
        (columnKey: string, direction: -1 | 1): void => {
            const current = renderedWidthsRef.current[columnKey] ?? MIN_COLUMN_WIDTH
            setColumnWidth(tableKey, columnKey, Math.max(MIN_COLUMN_WIDTH, current + direction * KEYBOARD_STEP))
        },
        [setColumnWidth, tableKey]
    )

    const resetWidth = useCallback(
        (columnKey: string): void => resetColumnWidth(tableKey, columnKey),
        [resetColumnWidth, tableKey]
    )

    return { resolveWidths, startResize, nudgeWidth, resetWidth }
}
