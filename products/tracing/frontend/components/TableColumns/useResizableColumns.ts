import { useActions, useValues } from 'kea'
import { PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from 'react'

import { tracingConfigLogic } from '../../tracingConfigLogic'
import { ColumnResizeHandleProps } from './ColumnResizeHandle'
import { MIN_COLUMN_WIDTH, ResizableColumnSpec, ResolvedColumnWidths, resolveColumnWidths } from './columnWidths'

/** How far one arrow key press moves a resize handle. */
const KEYBOARD_STEP = 16

export interface ResizableColumns {
    /** Call during render with the viewport width. The growing column absorbs what is left over. */
    resolveWidths: (availableWidth: number) => ResolvedColumnWidths
    startResize: (columnKey: string, event: ReactPointerEvent) => void
    nudgeWidth: (columnKey: string, direction: -1 | 1) => void
    resetWidth: (columnKey: string) => void
    /** False for the last column — it has nothing to its right to give or take space. */
    isResizable: (columnKey: string) => boolean
    /** `TableHeaderCell`'s `resize` prop for one column, or undefined if it isn't resizable. */
    resizeHandleProps: (columnKey: string, columnLabel: string) => Omit<ColumnResizeHandleProps, 'width'> | undefined
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
    const stopDragRef = useRef<(() => void) | null>(null)
    // The last render's resolved widths — a drag starts from what is on screen, not from the
    // default — and doubles as a memo cache: reusing the same widths object when none of its
    // inputs changed means unrelated re-renders (a sort click, a hover) don't hand every
    // virtualized row a new `widths` reference and force them all to re-render.
    const lastResolvedRef = useRef<{
        specs: ResizableColumnSpec[]
        stored: Record<string, number> | undefined
        dragged: typeof dragged
        availableWidth: number
        result: ResolvedColumnWidths
    } | null>(null)

    useEffect(() => () => stopDragRef.current?.(), [])

    const resolveWidths = (availableWidth: number): ResolvedColumnWidths => {
        const last = lastResolvedRef.current
        if (
            last &&
            last.specs === specs &&
            last.stored === stored &&
            last.dragged === dragged &&
            last.availableWidth === availableWidth
        ) {
            return last.result
        }
        const resolved = resolveColumnWidths(specs, stored, dragged, availableWidth)
        lastResolvedRef.current = { specs, stored, dragged, availableWidth, result: resolved }
        return resolved
    }

    const renderedWidth = (columnKey: string): number =>
        lastResolvedRef.current?.result.widths[columnKey] ?? MIN_COLUMN_WIDTH

    const isResizable = useCallback((columnKey: string) => specs[specs.length - 1]?.key !== columnKey, [specs])

    const startResize = useCallback(
        (columnKey: string, event: ReactPointerEvent): void => {
            event.preventDefault()
            // A drag cut short by a second pointer (e.g. two-finger touch) leaves its listeners
            // attached — clear it before starting a new one instead of orphaning it.
            stopDragRef.current?.()
            // Keep receiving move/up events even if the pointer leaves the handle, or the
            // window, before it's released.
            event.currentTarget.setPointerCapture(event.pointerId)

            const startX = event.clientX
            const startWidth = renderedWidth(columnKey)
            const widthAt = (clientX: number): number =>
                Math.max(MIN_COLUMN_WIDTH, Math.round(startWidth + clientX - startX))
            // A click with no movement shouldn't pin an auto-growing column to its current width.
            let moved = false

            const onMove = (moveEvent: PointerEvent): void => {
                moved = true
                setDragged({ columnKey, width: widthAt(moveEvent.clientX) })
            }
            const onUp = (upEvent: PointerEvent): void => {
                stopDragRef.current?.()
                if (moved) {
                    setColumnWidth(tableKey, columnKey, widthAt(upEvent.clientX))
                }
            }
            // A cancelled gesture (e.g. an interrupted touch drag) discards the in-progress width
            // instead of committing it.
            const onCancel = (): void => stopDragRef.current?.()

            stopDragRef.current = (): void => {
                document.removeEventListener('pointermove', onMove)
                document.removeEventListener('pointerup', onUp)
                document.removeEventListener('pointercancel', onCancel)
                document.body.classList.remove('cursor-col-resize', 'select-none')
                stopDragRef.current = null
                setDragged(null)
            }
            document.addEventListener('pointermove', onMove)
            document.addEventListener('pointerup', onUp)
            document.addEventListener('pointercancel', onCancel)
            // Hold the resize cursor and suppress text selection for the whole drag, not only while
            // the pointer stays over the handle.
            document.body.classList.add('cursor-col-resize', 'select-none')
        },
        [setColumnWidth, tableKey]
    )

    const nudgeWidth = useCallback(
        (columnKey: string, direction: -1 | 1): void => {
            const current = renderedWidth(columnKey)
            setColumnWidth(tableKey, columnKey, Math.max(MIN_COLUMN_WIDTH, current + direction * KEYBOARD_STEP))
        },
        [setColumnWidth, tableKey]
    )

    const resetWidth = useCallback(
        (columnKey: string): void => resetColumnWidth(tableKey, columnKey),
        [resetColumnWidth, tableKey]
    )

    const resizeHandleProps = useCallback(
        (columnKey: string, columnLabel: string): Omit<ColumnResizeHandleProps, 'width'> | undefined =>
            isResizable(columnKey)
                ? {
                      columnLabel,
                      onResizeStart: (event) => startResize(columnKey, event),
                      onNudge: (direction) => nudgeWidth(columnKey, direction),
                      onReset: () => resetWidth(columnKey),
                  }
                : undefined,
        [isResizable, startResize, nudgeWidth, resetWidth]
    )

    return { resolveWidths, startResize, nudgeWidth, resetWidth, isResizable, resizeHandleProps }
}
