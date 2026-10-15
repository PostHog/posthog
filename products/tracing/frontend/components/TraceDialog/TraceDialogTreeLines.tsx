import { rowConnectorLines, type TraceDialogRow } from './traceDialogRows'

// Indent shrinks with depth, so a deep span keeps room for its name: 16px for the first levels, then 12, then 8.
const INDENT_STEPS: [maxDepth: number, px: number][] = [
    [4, 16],
    [8, 12],
    [Infinity, 8],
]
// Past this depth rows stop indenting and show their depth instead. Folded chains keep most traces above it.
export const MAX_VISUAL_DEPTH = 16
// Where a level's line runs: the middle of the marker at the start of that level's rows.
const LINE_OFFSET_PX = 8

export function indentPx(depth: number): number {
    let px = 0
    for (let level = 0; level < Math.min(depth, MAX_VISUAL_DEPTH); level++) {
        px += INDENT_STEPS.find(([maxDepth]) => level < maxDepth)![1]
    }
    return px
}

/**
 * The tree lines left of a row: a line for each ancestor level that still has rows below, and an elbow
 * into this row from its parent's line. Rows past MAX_VISUAL_DEPTH draw none, since every level there
 * shares one position.
 */
export function TraceDialogTreeLines({ row }: { row: TraceDialogRow }): JSX.Element | null {
    if (row.depth === 0 || row.depth > MAX_VISUAL_DEPTH) {
        return null
    }
    const lines = rowConnectorLines(row)
    const parentLineX = indentPx(row.depth - 1) + LINE_OFFSET_PX
    return (
        <span className="absolute inset-y-0 left-0 pointer-events-none" aria-hidden>
            {lines.map((continues, level) =>
                continues ? (
                    <span
                        key={level}
                        className="absolute inset-y-0 w-px bg-border-bold"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ left: indentPx(level) + LINE_OFFSET_PX }}
                    />
                ) : null
            )}
            <span
                className="absolute top-0 w-px bg-border-bold"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: parentLineX, bottom: row.isLast ? '50%' : 0 }}
            />
            <span
                className="absolute top-1/2 h-px bg-border-bold"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: parentLineX, width: indentPx(row.depth) - parentLineX }}
            />
        </span>
    )
}
