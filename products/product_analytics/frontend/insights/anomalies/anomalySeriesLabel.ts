import { formatBreakdownLabel } from 'scenes/insights/utils'

import type { AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

// The scorer joins the parts of a multiple breakdown with "::", the same separator the insight legend shows.
const BREAKDOWN_PART_SEPARATOR = '::'

function anomalyBreakdownLabel(breakdownValue: string): string {
    return breakdownValue
        .split(BREAKDOWN_PART_SEPARATOR)
        .map((part) => formatBreakdownLabel(part, null, undefined, undefined))
        .join(BREAKDOWN_PART_SEPARATOR)
}

// The series label ends with the raw breakdown value, so a null or list value is formatted the way the insight legend formats it.
export function anomalySeriesLabel(series: Pick<AnomalySeriesApi, 'series_label' | 'breakdown_value'>): string | null {
    const { series_label: label, breakdown_value: breakdownValue } = series
    if (!breakdownValue) {
        return label || null
    }
    const breakdownLabel = anomalyBreakdownLabel(breakdownValue)
    if (!label) {
        return breakdownLabel
    }
    if (label.endsWith(breakdownValue)) {
        return label.slice(0, label.length - breakdownValue.length) + breakdownLabel
    }
    return label
}
