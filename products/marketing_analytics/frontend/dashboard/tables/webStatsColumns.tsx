import { humanFriendlyDuration } from 'lib/utils/durations'
import { VariationCell } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import type { BreakdownTableColumn, ComparedValue } from './breakdownTableColumn'
import type { WebStatsRow } from './webStatsRows'

const CountCell = VariationCell()
const DurationCell = VariationCell({ isDuration: true })
const RateCell = VariationCell({ isPercentage: true })
const BounceCell = VariationCell({ isPercentage: true, reverseColors: true })
const DecimalCell = VariationCell({ formatValue: (value) => value.toFixed(1) })

/** Derived per row rather than asked of the backend, which has no such column. */
export const pagesPerSession = (
    views: ComparedValue | undefined,
    sessions: ComparedValue | undefined
): ComparedValue | null => {
    if (!views || !sessions || !sessions[0]) {
        return null
    }
    const previous = views[1] !== null && sessions[1] !== null && sessions[1] !== 0 ? views[1] / sessions[1] : null
    return [views[0] / sessions[0], previous]
}

export const VISITORS_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'visitors',
    title: 'Visitors',
    tooltip: 'People with a pageview or screenview in the selected date range.',
    value: (row) => row.visitors ?? null,
    Cell: CountCell,
    exportLabel: 'Visitors',
}

export const VIEWS_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'views',
    title: 'Pageviews',
    shortTitle: 'Views',
    value: (row) => row.views ?? null,
    Cell: CountCell,
    exportLabel: 'Pageviews',
}

export const SESSIONS_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'sessions',
    title: 'Sessions',
    value: (row) => row.sessions ?? null,
    Cell: CountCell,
    exportLabel: 'Sessions',
}

export const SESSION_DURATION_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'session_duration',
    title: 'Avg. session duration',
    shortTitle: 'Duration',
    tooltip: 'The average length of sessions that started here.',
    value: (row) => row.session_duration ?? null,
    Cell: DurationCell,
    exportLabel: 'Avg. session duration',
    exportValue: (value) => humanFriendlyDuration(value) ?? String(value),
}

export const PAGES_PER_SESSION_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'pages_per_session',
    title: 'Pages per session',
    shortTitle: 'Pages',
    tooltip: 'Pageviews divided by sessions.',
    value: (row) => pagesPerSession(row.views, row.sessions),
    Cell: DecimalCell,
    exportLabel: 'Pages per session',
    exportValue: (value) => value.toFixed(2),
}

export const BOUNCE_RATE_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'bounce_rate',
    title: 'Bounce rate',
    shortTitle: 'Bounce',
    tooltip: 'Sessions that left without a second pageview or any meaningful interaction.',
    value: (row) => row.bounce_rate ?? null,
    Cell: BounceCell,
    exportLabel: 'Bounce rate',
}

export const CONVERSIONS_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'total_conversions',
    title: 'Conversions',
    value: (row) => row.total_conversions ?? null,
    Cell: CountCell,
    exportLabel: 'Conversions',
}

export const CONVERSION_RATE_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'conversion_rate',
    title: 'Conversion rate',
    shortTitle: 'Conv. rate',
    tooltip: 'People who completed the goal, divided by visitors.',
    value: (row) => row.conversion_rate ?? null,
    Cell: RateCell,
    exportLabel: 'Conversion rate',
}
