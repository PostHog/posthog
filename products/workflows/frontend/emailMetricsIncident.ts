import { Dayjs, dayjs } from 'lib/dayjs'

// Metrics are stored in hourly buckets, so the window covers the whole affected hour.
export const EMAIL_METRICS_INCIDENT_WINDOW = {
    start: dayjs.utc('2026-11-03T11:00:00Z'),
    end: dayjs.utc('2026-11-03T12:00:00Z'),
}

export function overlapsEmailMetricsIncident(dateFrom: Dayjs, dateTo: Dayjs): boolean {
    return dateFrom.isBefore(EMAIL_METRICS_INCIDENT_WINDOW.end) && !dateTo.isBefore(EMAIL_METRICS_INCIDENT_WINDOW.start)
}
