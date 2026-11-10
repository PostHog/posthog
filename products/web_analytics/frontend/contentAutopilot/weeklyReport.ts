import { dayjs } from 'lib/dayjs'

import type {
    AEOWeeklyReportApi,
    WeeklyReportPageRoleEnumApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import type { KpiCardContent } from './promptReport'

export const WEEKLY_REPORT_PAGE_ROLE_LABELS: Record<WeeklyReportPageRoleEnumApi, string> = {
    owned_gained: 'Your page that gained most',
    owned_lost: 'Your page that lost most',
    competitor_gained: 'Competitor page that gained most',
}

const trimmedTenths = (value: number): string => value.toFixed(1).replace(/\.0$/, '')

/** A share (0-1) as a percentage, the way the delivered report writes it. */
export const formatWeeklyRate = (rate: number | null): string =>
    rate === null ? 'no answers' : `${trimmedTenths(rate * 100)}%`

/** A change between two shares, in percentage points. */
export const formatWeeklyChange = (change: number | null): string => {
    if (change === null) {
        return 'new this week'
    }
    const points = trimmedTenths(Math.abs(change) * 100)
    if (points === '0') {
        return 'no change'
    }
    return `${change > 0 ? '+' : '-'}${points} ${points === '1' ? 'pt' : 'pts'}`
}

export const weeklyChangeStatus = (change: number | null): 'success' | 'danger' | 'muted' =>
    change === null || Math.abs(change) < 0.0005 ? 'muted' : change > 0 ? 'success' : 'danger'

export const weeklyReportPeriod = (report: Pick<AEOWeeklyReportApi, 'window_from' | 'window_to'>): string =>
    `${dayjs(report.window_from).format('MMM D')} to ${dayjs(report.window_to).format('MMM D')}`

export const weeklyTopicName = (topic: string): string => topic || 'No topic'

/** The URL without its scheme, query or trailing slash, as people read it. */
export const weeklyPageLabel = (url: string): string => {
    const label = url
        .replace(/^[a-z][a-z0-9+.-]*:\/\//i, '')
        .split(/[?#]/)[0]
        .replace(/\/+$/, '')
    return label || url
}

/** The KPI card content for one scorecard rate. */
export const weeklyKpi = (rate: number | null, previous: number | null, change: number | null): KpiCardContent => ({
    value: formatWeeklyRate(rate),
    note: `${formatWeeklyRate(previous)} the week before`,
    delta:
        change === null
            ? null
            : {
                  label: formatWeeklyChange(change),
                  direction: weeklyChangeStatus(change) === 'muted' ? 'flat' : change > 0 ? 'up' : 'down',
                  tooltip: 'Change against the 7 days before, in percentage points.',
              },
})
