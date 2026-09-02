import type { _MetricAnomalyDimensionApi } from './generated/api.schemas'

/** One label value's contribution to a spike, shaped for display. */
export interface MetricTopMoverRow {
    key: string
    label: string
    baselineValue: number
    anomalyValue: number
    /** How far it moved, as a positive percentage. Meaningless when `isNew`. */
    percent: number
    direction: 'up' | 'down'
    /** Absent from the baseline window, so there is no ratio to quote — it simply appeared. */
    isNew: boolean
}

/**
 * Rank the label values behind a metric's move, largest change first.
 *
 * The backend already computes this attribution (`anomaly.py`); this only turns it into
 * something readable. A value with no baseline is reported as new rather than as a huge
 * percentage: the backend yields the anomaly value itself for a zero baseline, so a ratio
 * there says nothing, and "appeared" is the finding anyway.
 */
export const topMoverRows = (movers: _MetricAnomalyDimensionApi[]): MetricTopMoverRow[] =>
    movers
        .map((mover) => {
            const isNew = mover.baseline_value === 0
            return {
                key: mover.key,
                label: mover.label,
                baselineValue: mover.baseline_value,
                anomalyValue: mover.anomaly_value,
                percent: isNew ? 0 : Math.abs(Math.round((mover.change_ratio - 1) * 100)),
                direction: (mover.anomaly_value >= mover.baseline_value ? 'up' : 'down') as 'up' | 'down',
                isNew,
            }
        })
        // A value that appeared out of nothing outranks any percentage change, which is why it
        // cannot share the percentage ordering.
        .sort((a, b) => Number(b.isNew) - Number(a.isNew) || b.percent - a.percent)
