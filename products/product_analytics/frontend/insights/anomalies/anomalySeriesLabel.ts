import { formatBreakdownLabel } from 'scenes/insights/utils'

import type { AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

const BREAKDOWN_PART_SEPARATOR = '::'

function anomalyBreakdownLabel(breakdownValue: string): string {
    return breakdownValue
        .split(BREAKDOWN_PART_SEPARATOR)
        .map((part) => formatBreakdownLabel(part, null, undefined, undefined))
        .join(BREAKDOWN_PART_SEPARATOR)
}

// The series label ends with the raw breakdown value, so each "::" part of it gets the insight legend's formatting.
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
