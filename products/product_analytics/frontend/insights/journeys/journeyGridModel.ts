import { PathsV2Item, PathsV2Results } from '~/queries/schema/schema-general'

export const OTHER_ROW_KEY = 'other'
const DROP_OFF_ROW_KEY = 'dropOff'

export type JourneyGridRowKind = 'item' | 'other' | 'dropOff'

export interface JourneyGridRow {
    /** Unique within the column; ribbons reference rows by (stepIndex, key). */
    key: string
    kind: JourneyGridRowKind
    item: PathsV2Item | null
    label: string
    count: number
    /** Share of the column's displayed total; 0 when the total is 0. */
    fraction: number
}

export interface JourneyGridColumn {
    stepIndex: number
    /** Named item rows by count descending, then the other row, then the drop-off row. */
    rows: JourneyGridRow[]
    /** The column's displayed unique-actor total: named rows plus the other row. */
    total: number
}

export interface JourneyGridRibbon {
    key: string
    /** Column index of the source row; the target row sits at sourceStep + 1. */
    sourceStep: number
    sourceKey: string
    targetKey: string
    count: number
    /** Share of the source row's count, shown in the ribbon tooltip. */
    fractionOfSource: number
    sourceLabel: string
    targetLabel: string
    /** The endpoints' path items; null for an endpoint on the column's other row. */
    sourceItem: PathsV2Item | null
    targetItem: PathsV2Item | null
    /** Position-free count of the transition at any step; only on open-mode named-named edges. */
    anyStepCount: number | null
}

export interface JourneyGridModel {
    columns: JourneyGridColumn[]
    ribbons: JourneyGridRibbon[]
    maxRibbonCount: number
}

/** The active hover-preview chain resolved against the grid: per-card chain counts plus the
 * ribbons connecting them. Card keys are `${stepIndex}:${rowKey}`, ribbon keys match ribbon.key. */
export interface JourneyChainHighlight {
    chain: PathsV2Item[]
    countByCardKey: Record<string, number>
    ribbonKeys: Set<string>
}

export function chainCardKey(stepIndex: number, item: PathsV2Item): string {
    return `${stepIndex}:${journeyItemKey(item)}`
}

export function isCardOnChain(chain: PathsV2Item[] | null, stepIndex: number, rowKey: string): boolean {
    return (
        chain !== null &&
        stepIndex < chain.length &&
        journeyItemKey(chain[stepIndex]) === rowKey &&
        rowKey !== OTHER_ROW_KEY
    )
}

export function journeyItemKey(item: PathsV2Item): string {
    // The label distinguishes null (source without a naming property) from '' (missing property value)
    return `item:${JSON.stringify([item.event, item.label ?? null])}`
}

export function journeyItemLabel(item: PathsV2Item): string {
    if (item.label == null) {
        return item.event
    }
    return item.label === '' ? '(empty)' : item.label
}

export function buildJourneyGridModel(results: PathsV2Results | null): JourneyGridModel {
    if (!results || results.steps.length === 0) {
        return { columns: [], ribbons: [], maxRibbonCount: 0 }
    }

    const steps = [...results.steps].sort((a, b) => a.stepIndex - b.stepIndex)

    const columns: JourneyGridColumn[] = steps.map((step) => {
        const total = step.rows.reduce((sum, row) => sum + row.count, 0) + step.otherCount
        const rows: JourneyGridRow[] = step.rows.map((row) => ({
            key: journeyItemKey(row.item),
            kind: 'item' as const,
            item: row.item,
            label: journeyItemLabel(row.item),
            count: row.count,
            fraction: total > 0 ? row.count / total : 0,
        }))
        if (step.otherCount > 0) {
            rows.push({
                key: OTHER_ROW_KEY,
                kind: 'other',
                item: null,
                label: 'Other',
                count: step.otherCount,
                fraction: total > 0 ? step.otherCount / total : 0,
            })
        }
        if (step.dropOffCount > 0) {
            rows.push({
                key: DROP_OFF_ROW_KEY,
                kind: 'dropOff',
                item: null,
                label: 'Ends here',
                count: step.dropOffCount,
                fraction: total > 0 ? step.dropOffCount / total : 0,
            })
        }
        return { stepIndex: step.stepIndex, rows, total }
    })

    const rowByStepAndKey = new Map<string, JourneyGridRow>()
    for (const column of columns) {
        for (const row of column.rows) {
            rowByStepAndKey.set(`${column.stepIndex}:${row.key}`, row)
        }
    }

    const ribbons: JourneyGridRibbon[] = []
    for (const edge of results.edges) {
        if (edge.count <= 0) {
            continue
        }
        const sourceKey = edge.source ? journeyItemKey(edge.source) : OTHER_ROW_KEY
        const targetKey = edge.target ? journeyItemKey(edge.target) : OTHER_ROW_KEY
        const sourceRow = rowByStepAndKey.get(`${edge.stepIndex}:${sourceKey}`)
        const targetRow = rowByStepAndKey.get(`${edge.stepIndex + 1}:${targetKey}`)
        // The runner buckets edge endpoints the same way as node rows, so both should resolve;
        // skip defensively rather than render a dangling ribbon.
        if (!sourceRow || !targetRow) {
            continue
        }
        ribbons.push({
            key: `${edge.stepIndex}:${sourceKey}→${targetKey}`,
            sourceStep: edge.stepIndex,
            sourceKey,
            targetKey,
            count: edge.count,
            fractionOfSource: sourceRow.count > 0 ? edge.count / sourceRow.count : 0,
            sourceLabel: sourceRow.label,
            targetLabel: targetRow.label,
            sourceItem: edge.source ?? null,
            targetItem: edge.target ?? null,
            anyStepCount: edge.anyStepCount ?? null,
        })
    }

    const maxRibbonCount = ribbons.reduce((max, ribbon) => Math.max(max, ribbon.count), 0)

    return { columns, ribbons, maxRibbonCount }
}

/** A closed band from the source card's right edge to the target card's left edge. */
export function ribbonPath(x0: number, y0: number, t0: number, x1: number, y1: number, t1: number): string {
    const xm = (x0 + x1) / 2
    return [
        `M ${x0},${y0}`,
        `C ${xm},${y0} ${xm},${y1} ${x1},${y1}`,
        `L ${x1},${y1 + t1}`,
        `C ${xm},${y1 + t1} ${xm},${y0 + t0} ${x0},${y0 + t0}`,
        'Z',
    ].join(' ')
}
