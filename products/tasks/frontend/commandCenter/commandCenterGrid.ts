/** Columns by rows, like PostHog Desktop's command center presets. */
export type CommandCenterLayout = '1x1' | '2x1' | '2x2' | '3x2'

export const COMMAND_CENTER_LAYOUTS: CommandCenterLayout[] = ['1x1', '2x1', '2x2', '3x2']

/** A tile holds a session id, or `null` when it is empty. */
export type CommandCenterCells = (string | null)[]

export function layoutColumns(layout: CommandCenterLayout): number {
    return Number(layout.split('x')[0])
}

export function layoutCellCount(layout: CommandCenterLayout): number {
    const [cols, rows] = layout.split('x').map(Number)
    return cols * rows
}

/** Fits the cells to a new tile count. A smaller layout moves the sessions it cuts off into its empty tiles first. */
export function resizeCells(cells: CommandCenterCells, count: number): CommandCenterCells {
    const kept = Array.from({ length: count }, (_, index) => cells[index] ?? null)
    const cutOff = cells.slice(count).filter((cell): cell is string => !!cell)
    return kept.map((cell) => cell ?? cutOff.shift() ?? null)
}

/** Puts a session in a tile. A session shows in one tile only, so its old tile empties. */
export function placeSession(cells: CommandCenterCells, index: number, sessionId: string): CommandCenterCells {
    return cells.map((cell, cellIndex) => (cellIndex === index ? sessionId : cell === sessionId ? null : cell))
}
