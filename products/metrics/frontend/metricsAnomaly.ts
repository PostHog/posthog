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
    /** Whether clicking it can narrow the chart. False for a mover whose label value is empty. */
    isFilterable: boolean
}

/**
 * Shape the label values behind a metric's move for display.
 *
 * Order comes from the backend and is preserved. `anomaly.py` ranks by a magnitude that blends
 * ratio with scale, precisely so a tiny series that tripled does not outrank a large one that
 * moved a lot — re-sorting on percentage here would undo that and put noise at the top.
 *
 * A value with no baseline is reported as new rather than as a huge percentage: the backend
 * yields the anomaly value itself for a zero baseline, so a ratio there says nothing.
 */
export const topMoverRows = (movers: _MetricAnomalyDimensionApi[]): MetricTopMoverRow[] =>
    movers.map((mover) => {
        const isNew = mover.baseline_value === 0
        return {
            key: mover.key,
            label: mover.label,
            baselineValue: mover.baseline_value,
            anomalyValue: mover.anomaly_value,
            percent: isNew ? 0 : Math.abs(Math.round((mover.change_ratio - 1) * 100)),
            // Read off the raw values rather than the ratio, which inverts on a negative baseline.
            direction: (mover.anomaly_value >= mover.baseline_value ? 'up' : 'down') as 'up' | 'down',
            isNew,
            // A group-by on a key some series lack reports an empty label. No equality filter
            // expresses that, so the row stays informative but is not offered as a drilldown.
            isFilterable: mover.label !== '',
        }
    })
