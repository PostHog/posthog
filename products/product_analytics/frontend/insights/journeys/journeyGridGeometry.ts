import { JourneyGridModel, JourneyGridRibbon, JourneyGridRow } from './journeyGridModel'

export const CARD_WIDTH = 224
export const COLUMN_GAP = 104
export const CARD_HEIGHT = 66
export const ROW_GAP = 14
export const HEADER_HEIGHT = 28
export const PORT_TOP_OFFSET = 6
export const PORT_GAP = 2
export const MAX_RIBBON_THICKNESS = 36
export const MIN_RIBBON_THICKNESS = 2

export interface CardGeometry {
    row: JourneyGridRow
    stepIndex: number
    x: number
    y: number
}

export interface RibbonGeometry {
    ribbon: JourneyGridRibbon
    /** Band thickness at the source card's edge; the target edge can differ when one side is
     * squeezed to fit its card. */
    sourceThickness: number
    targetThickness: number
    fromX: number
    fromY: number
    toX: number
    toY: number
}

export interface JourneyGridGeometry {
    cards: CardGeometry[]
    ribbons: RibbonGeometry[]
    chartWidth: number
    chartHeight: number
}

export function cardKey(stepIndex: number, rowKey: string): string {
    return `${stepIndex}:${rowKey}`
}

interface ResolvedRibbon {
    ribbon: JourneyGridRibbon
    source: CardGeometry
    target: CardGeometry
    sourceCardKey: string
    targetCardKey: string
}

const PORT_STACK_HEIGHT = CARD_HEIGHT - 2 * PORT_TOP_OFFSET

/**
 * Thickness per ribbon of one card side (a card's out-stack or in-stack): proportional to count,
 * squeezed so the stack always fits within the card's height. Counts are deduped per element, so
 * a side's ribbon counts can sum past the card's own count and proportional thickness alone can
 * overflow the card.
 */
function fitThicknesses(sideRibbons: JourneyGridRibbon[], baseThickness: (count: number) => number): number[] {
    const base = sideRibbons.map((ribbon) => baseThickness(ribbon.count))
    const gaps = (sideRibbons.length - 1) * PORT_GAP
    if (base.reduce((sum, thickness) => sum + thickness, 0) + gaps <= PORT_STACK_HEIGHT) {
        return base
    }
    const slack = PORT_STACK_HEIGHT - gaps - sideRibbons.length * MIN_RIBBON_THICKNESS
    if (slack <= 0) {
        // Unreachable within the schema's rows-per-step bounds; split evenly rather than overflow.
        return sideRibbons.map(() => Math.max(1, (PORT_STACK_HEIGHT - gaps) / sideRibbons.length))
    }
    const countSum = sideRibbons.reduce((sum, ribbon) => sum + ribbon.count, 0)
    return sideRibbons.map((ribbon) => MIN_RIBBON_THICKNESS + (slack * ribbon.count) / Math.max(countSum, 1))
}

export function computeJourneyGridGeometry(model: JourneyGridModel): JourneyGridGeometry {
    const cardByKey = new Map<string, CardGeometry>()
    const cards: CardGeometry[] = []
    let maxCardBottom = 0
    model.columns.forEach((column, columnIndex) => {
        let y = HEADER_HEIGHT
        for (const row of column.rows) {
            const card = { row, stepIndex: column.stepIndex, x: columnIndex * (CARD_WIDTH + COLUMN_GAP), y }
            cardByKey.set(cardKey(column.stepIndex, row.key), card)
            cards.push(card)
            y += CARD_HEIGHT + ROW_GAP
        }
        maxCardBottom = Math.max(maxCardBottom, y - ROW_GAP)
    })

    // Normalize against the busiest column's total rather than the largest edge: when every edge
    // carries the same small count, edge-relative scaling would render all of them at maximum
    // thickness even though each is a sliver of the population.
    const maxColumnTotal = model.columns.reduce((max, column) => Math.max(max, column.total), 0)
    const baseThickness = (count: number): number =>
        Math.max(MIN_RIBBON_THICKNESS, (count / Math.max(maxColumnTotal, 1)) * MAX_RIBBON_THICKNESS)

    // Resolve each ribbon's cards once, then stack the ports on each card side in the vertical
    // order of the connected cards, so ribbons out of one card never cross at the card edge.
    const resolvedRibbons: ResolvedRibbon[] = model.ribbons.flatMap((ribbon) => {
        const sourceCardKey = cardKey(ribbon.sourceStep, ribbon.sourceKey)
        const targetCardKey = cardKey(ribbon.sourceStep + 1, ribbon.targetKey)
        const source = cardByKey.get(sourceCardKey)
        const target = cardByKey.get(targetCardKey)
        return source && target ? [{ ribbon, source, target, sourceCardKey, targetCardKey }] : []
    })
    resolvedRibbons.sort((a, b) => a.source.y - b.source.y || a.target.y - b.target.y)

    const bySide = (keyOf: (resolved: ResolvedRibbon) => string): Map<string, number> => {
        const groups = new Map<string, ResolvedRibbon[]>()
        for (const resolved of resolvedRibbons) {
            const key = keyOf(resolved)
            groups.set(key, [...(groups.get(key) ?? []), resolved])
        }
        const thicknessByRibbonKey = new Map<string, number>()
        for (const group of groups.values()) {
            const thicknesses = fitThicknesses(
                group.map((resolved) => resolved.ribbon),
                baseThickness
            )
            group.forEach((resolved, index) => thicknessByRibbonKey.set(resolved.ribbon.key, thicknesses[index]))
        }
        return thicknessByRibbonKey
    }
    const sourceThicknesses = bySide((resolved) => resolved.sourceCardKey)
    const targetThicknesses = bySide((resolved) => resolved.targetCardKey)

    const outCursor = new Map<string, number>()
    const inCursor = new Map<string, number>()
    const ribbons: RibbonGeometry[] = resolvedRibbons.map(
        ({ ribbon, source, target, sourceCardKey, targetCardKey }) => {
            const sourceThickness = sourceThicknesses.get(ribbon.key) ?? MIN_RIBBON_THICKNESS
            const targetThickness = targetThicknesses.get(ribbon.key) ?? MIN_RIBBON_THICKNESS
            const fromY = source.y + PORT_TOP_OFFSET + (outCursor.get(sourceCardKey) ?? 0)
            const toY = target.y + PORT_TOP_OFFSET + (inCursor.get(targetCardKey) ?? 0)
            outCursor.set(sourceCardKey, (outCursor.get(sourceCardKey) ?? 0) + sourceThickness + PORT_GAP)
            inCursor.set(targetCardKey, (inCursor.get(targetCardKey) ?? 0) + targetThickness + PORT_GAP)
            return {
                ribbon,
                sourceThickness,
                targetThickness,
                fromX: source.x + CARD_WIDTH,
                fromY,
                toX: target.x,
                toY,
            }
        }
    )

    const chartWidth = model.columns.length * (CARD_WIDTH + COLUMN_GAP) - COLUMN_GAP
    const chartHeight = maxCardBottom + 16
    return { cards, ribbons, chartWidth, chartHeight }
}
