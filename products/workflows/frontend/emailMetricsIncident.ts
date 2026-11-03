import { Dayjs, dayjs } from 'lib/dayjs'

export const EMAIL_METRICS_INCIDENT_WINDOW = {
    start: dayjs.utc('2026-11-03T10:58:00Z'),
    end: dayjs.utc('2026-11-03T11:36:00Z'),
}

// Metrics are stored in hourly buckets, so a range that touches any hour the incident touched includes bad data.
const AFFECTED_BUCKETS = {
    start: EMAIL_METRICS_INCIDENT_WINDOW.start.startOf('hour'),
    end: EMAIL_METRICS_INCIDENT_WINDOW.end.startOf('hour').add(1, 'hour'),
}

export function overlapsEmailMetricsIncident(dateFrom: Dayjs, dateTo: Dayjs): boolean {
    return dateFrom.isBefore(AFFECTED_BUCKETS.end) && !dateTo.isBefore(AFFECTED_BUCKETS.start)
}
