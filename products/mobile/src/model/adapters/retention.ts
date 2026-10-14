import { asRecord, isRecord } from '@/lib/records'

import type { RetentionCellView, RetentionCohortView, RetentionPeriodUnit, RetentionView } from '../views'

type JsonRecord = Record<string, unknown>

const PERIODS: Record<string, RetentionPeriodUnit> = { Hour: 'hour', Day: 'day', Week: 'week', Month: 'month' }

const PERIOD_MS: Record<Exclude<RetentionPeriodUnit, 'month'>, number> = {
    hour: 3_600_000,
    day: 86_400_000,
    week: 7 * 86_400_000,
}

function finite(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function periodStart(cohortStart: number, period: RetentionPeriodUnit, index: number): number {
    if (period === 'month') {
        const date = new Date(cohortStart)
        date.setUTCMonth(date.getUTCMonth() + index)
        return date.getTime()
    }
    return cohortStart + index * PERIOD_MS[period]
}

function cohortView(
    row: JsonRecord,
    index: number,
    period: RetentionPeriodUnit,
    reference: RetentionView['reference'],
    now: number
): RetentionCohortView | null {
    const date = typeof row.date === 'string' ? row.date : null
    const start = date ? Date.parse(date) : Number.NaN
    if (!date || !Number.isFinite(start)) {
        return null
    }
    const counts = (Array.isArray(row.values) ? row.values.filter(isRecord) : []).map(
        (value) => finite(value.count) ?? 0
    )
    const size = counts[0] ?? 0
    const cells: RetentionCellView[] = []
    for (let offset = 0; offset < counts.length; offset += 1) {
        // The server answers every period for every cohort. Periods that have not started yet are zeros, not data.
        if (periodStart(start, period, offset) > now) {
            break
        }
        const count = counts[offset] ?? 0
        const base = reference === 'previous' && offset > 0 ? (counts[offset - 1] ?? 0) : size
        cells.push({ count, percent: base > 0 ? (count / base) * 100 : 0 })
    }
    return { key: `${index}:${date}`, date, size, cells }
}

/**
 * The cohort grid of a retention insight, with percents as the web computes them. Breakdowns and sums or averages
 * of a property give null: the grid would mix cohorts or read amounts as people, so those open on the web.
 */
export function retentionView(query: unknown, result: unknown, now: number): RetentionView | null {
    const source = asRecord(asRecord(query)?.source) ?? asRecord(query)
    if (source?.kind !== 'RetentionQuery' || !Array.isArray(result)) {
        return null
    }
    const filter = asRecord(source.retentionFilter)
    const aggregation = filter?.aggregationType
    if (aggregation !== undefined && aggregation !== null && aggregation !== 'count') {
        return null
    }
    const rows = result.filter(isRecord)
    if (rows.some((row) => row.breakdown_value !== undefined && row.breakdown_value !== null)) {
        return null
    }
    const period = (typeof filter?.period === 'string' ? PERIODS[filter.period] : undefined) ?? 'day'
    const reference = filter?.retentionReference === 'previous' ? 'previous' : 'total'
    const cohorts = rows
        .map((row, index) => cohortView(row, index, period, reference, now))
        .filter((cohort): cohort is RetentionCohortView => cohort !== null)
    const widest = rows.reduce<JsonRecord[]>((labels, row) => {
        const values = Array.isArray(row.values) ? row.values.filter(isRecord) : []
        return values.length > labels.length ? values : labels
    }, [])
    const unit = `${period.charAt(0).toUpperCase()}${period.slice(1)}`
    const periodLabels = widest.map((value, index) =>
        typeof value.label === 'string' && value.label !== '' ? value.label : `${unit} ${index}`
    )
    return { period, periodLabels, cohorts, reference }
}
