import { JourneyGridModel, JourneyGridRibbon, JourneyGridRow } from './journeyGridModel'

// One shared px-per-actor scale drives both bar heights and ribbon thicknesses, so flows
// visually conserve: a node's out-ribbons tile its bar edge instead of floating beside it.
export const COLUMN_PITCH = 280
export const BAR_WIDTH = 88
export const LABEL_BLOCK_HEIGHT = 40
export const DROP_OFF_BLOCK_HEIGHT = 36
export const ROW_GAP = 20
export const HEADER_HEIGHT = 28
/** Height budget for the tallest column's bars; smaller columns scale down from it. */
export const BAR_HEIGHT_BUDGET = 420
export const MIN_BAR_HEIGHT = 6
export const MIN_RIBBON_THICKNESS = 1.5

export interface JourneyLayoutRow {
    row: JourneyGridRow
    stepIndex: number
    /** Column left edge; the label block and bar both start here. */
    x: number
    /** Label block top. */
    labelY: number
    /** Bar top; equals labelY + LABEL_BLOCK_HEIGHT. Unused for drop-off rows. */
    barY: number
    /** 0 for drop-off rows, which render as text only. */
    barHeight: number
}

export interface JourneyLayoutRibbon {
    ribbon: JourneyGridRibbon
    fromX: number
    fromY: number
    /** Band thickness at the source bar's edge. */
    fromThickness: number
    toX: number
    toY: number
    /** Band thickness at the target bar's edge; differs from the source end when squeezed. */
    toThickness: number
}

export interface JourneyGridLayout {
    rows: JourneyLayoutRow[]
    ribbons: JourneyLayoutRibbon[]
    width: number
    height: number
}

function rowKey(stepIndex: number, key: string): string {
    return `${stepIndex}:${key}`
}

export function buildJourneyGridLayout(model: JourneyGridModel): JourneyGridLayout {
    // Drop-off counts overlap the column's other rows (a journey ending at a step is also counted
    // at that step), so they stay out of the actor sum that sets the scale.
    let maxColumnActors = 0
    for (const column of model.columns) {
        const actors = column.rows.reduce((sum, row) => (row.kind === 'dropOff' ? sum : sum + row.count), 0)
        maxColumnActors = Math.max(maxColumnActors, actors)
    }
    const scale = maxColumnActors > 0 ? BAR_HEIGHT_BUDGET / maxColumnActors : 0

    const rowByKey = new Map<string, JourneyLayoutRow>()
    const rows: JourneyLayoutRow[] = []
    let height = 0
    model.columns.forEach((column, columnIndex) => {
        let y = HEADER_HEIGHT
        for (const row of column.rows) {
            const barHeight = row.kind === 'dropOff' ? 0 : Math.max(MIN_BAR_HEIGHT, row.count * scale)
            const layoutRow: JourneyLayoutRow = {
                row,
                stepIndex: column.stepIndex,
                x: columnIndex * COLUMN_PITCH,
                labelY: y,
                barY: y + LABEL_BLOCK_HEIGHT,
                barHeight,
            }
            rowByKey.set(rowKey(column.stepIndex, row.key), layoutRow)
            rows.push(layoutRow)
            y += (row.kind === 'dropOff' ? DROP_OFF_BLOCK_HEIGHT : LABEL_BLOCK_HEIGHT + barHeight) + ROW_GAP
        }
        height = Math.max(height, y - ROW_GAP)
    })

    // Stack the ports on each bar edge in the vertical order of the connected bars, so ribbons
    // out of one bar never cross at the edge. Ports are contiguous, tiling the edge like a sankey.
    const resolved = model.ribbons.flatMap((ribbon) => {
        const source = rowByKey.get(rowKey(ribbon.sourceStep, ribbon.sourceKey))
        const target = rowByKey.get(rowKey(ribbon.sourceStep + 1, ribbon.targetKey))
        return source && target && source.row.kind !== 'dropOff' && target.row.kind !== 'dropOff'
            ? [{ ribbon, source, target }]
            : []
    })
    resolved.sort((a, b) => a.source.barY - b.source.barY || a.target.barY - b.target.barY)

    const baseThickness = (ribbon: JourneyGridRibbon): number => Math.max(MIN_RIBBON_THICKNESS, ribbon.count * scale)

    // In open mode an actor with several journeys can appear on more than one edge of a node, and
    // minimum thicknesses inflate hair-thin bands, so a bar's ports can sum past its height;
    // squeeze that end's bands proportionally to keep them tiling within the edge.
    const outTotal = new Map<string, number>()
    const inTotal = new Map<string, number>()
    for (const { ribbon } of resolved) {
        const thickness = baseThickness(ribbon)
        const sourceKey = rowKey(ribbon.sourceStep, ribbon.sourceKey)
        const targetKey = rowKey(ribbon.sourceStep + 1, ribbon.targetKey)
        outTotal.set(sourceKey, (outTotal.get(sourceKey) ?? 0) + thickness)
        inTotal.set(targetKey, (inTotal.get(targetKey) ?? 0) + thickness)
    }
    const squeeze = (total: number | undefined, barHeight: number): number =>
        total && total > barHeight ? barHeight / total : 1

    const outCursor = new Map<string, number>()
    const inCursor = new Map<string, number>()
    const ribbons: JourneyLayoutRibbon[] = resolved.map(({ ribbon, source, target }) => {
        const sourceKey = rowKey(ribbon.sourceStep, ribbon.sourceKey)
        const targetKey = rowKey(ribbon.sourceStep + 1, ribbon.targetKey)
        const base = baseThickness(ribbon)
        const fromThickness = base * squeeze(outTotal.get(sourceKey), source.barHeight)
        const toThickness = base * squeeze(inTotal.get(targetKey), target.barHeight)
        const fromY = source.barY + (outCursor.get(sourceKey) ?? 0)
        const toY = target.barY + (inCursor.get(targetKey) ?? 0)
        outCursor.set(sourceKey, (outCursor.get(sourceKey) ?? 0) + fromThickness)
        inCursor.set(targetKey, (inCursor.get(targetKey) ?? 0) + toThickness)
        return {
            ribbon,
            fromX: source.x + BAR_WIDTH,
            fromY,
            fromThickness,
            toX: target.x,
            toY,
            toThickness,
        }
    })

    const labelWidth = COLUMN_PITCH - 24
    const width = model.columns.length > 0 ? (model.columns.length - 1) * COLUMN_PITCH + labelWidth : 0
    return { rows, ribbons, width, height: height + 16 }
}
