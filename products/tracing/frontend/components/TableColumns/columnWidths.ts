/** Narrowest a column can be dragged, so a column can never disappear entirely. */
export const MIN_COLUMN_WIDTH = 56
/** Widest the growing column gets from leftover space. Dragging past this is still allowed. */
export const MAX_AUTO_GROW_WIDTH = 520

export interface ResizableColumnSpec {
    key: string
    /** Width in px before anyone resizes the column. */
    width: number
    /** Takes the space left over in the viewport, up to a cap. At most one column per table. */
    grow?: boolean
}

export interface ResolvedColumnWidths {
    widths: Record<string, number>
    /** Combined width of every column. The row is never narrower than this. */
    totalWidth: number
}

/**
 * Width of every column for one render, in precedence order: the live drag, then the stored
 * width, then the default.
 */
export function resolveColumnWidths(
    specs: ResizableColumnSpec[],
    storedWidths: Record<string, number> | undefined,
    draggedWidth: { columnKey: string; width: number } | null,
    availableWidth: number
): ResolvedColumnWidths {
    const widths: Record<string, number> = {}
    let totalWidth = 0
    for (const spec of specs) {
        const width =
            draggedWidth?.columnKey === spec.key ? draggedWidth.width : (storedWidths?.[spec.key] ?? spec.width)
        // Stored widths outlive the code that wrote them, so a corrupt one falls back to the
        // default rather than collapsing the column for good.
        widths[spec.key] = Number.isFinite(width) ? Math.max(MIN_COLUMN_WIDTH, Math.round(width)) : spec.width
        totalWidth += widths[spec.key]
    }

    const growSpec = specs.find((spec) => spec.grow)
    // A column with a width of its own stops growing. If it kept taking the leftover space, that
    // space would refill after every drag and the column would look stuck.
    if (growSpec && storedWidths?.[growSpec.key] === undefined && draggedWidth?.columnKey !== growSpec.key) {
        const extra = Math.min(
            Math.max(availableWidth - totalWidth, 0),
            Math.max(MAX_AUTO_GROW_WIDTH - widths[growSpec.key], 0)
        )
        widths[growSpec.key] += extra
        totalWidth += extra
    }

    return { widths, totalWidth }
}
