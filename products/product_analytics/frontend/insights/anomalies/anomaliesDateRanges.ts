export interface AnomaliesDateRange {
    // Passed as `date_from` to the anomaly search.
    dateFrom: string
    label: string
}

// Shortest first, so the empty state can offer the next one.
export const ANOMALIES_DATE_RANGES: AnomaliesDateRange[] = [
    { dateFrom: '-24h', label: 'Last 24 hours' },
    { dateFrom: '-7d', label: 'Last 7 days' },
    { dateFrom: '-14d', label: 'Last 14 days' },
    { dateFrom: '-30d', label: 'Last 30 days' },
    { dateFrom: '-90d', label: 'Last 90 days' },
]

export function anomaliesDateRangeLabel(dateFrom: string): string {
    return ANOMALIES_DATE_RANGES.find((range) => range.dateFrom === dateFrom)?.label ?? 'Selected range'
}

export function longerAnomaliesDateRange(dateFrom: string): AnomaliesDateRange | null {
    const index = ANOMALIES_DATE_RANGES.findIndex((range) => range.dateFrom === dateFrom)
    return index === -1 ? null : (ANOMALIES_DATE_RANGES[index + 1] ?? null)
}
