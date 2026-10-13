import { humanFriendlyDuration } from 'lib/utils/durations'

import type { BreakdownTableColumn, ComparedValue } from './breakdownTableColumn'
import type { WebStatsRow } from './webStatsRows'

/** Divides two compared values, keeping the previous period only when both sides have one. */
export const ratio = (
    numerator: ComparedValue | undefined,
    denominator: ComparedValue | undefined
): ComparedValue | null => {
    if (!numerator || !denominator || !denominator[0]) {
        return null
    }
    const previous =
        numerator[1] !== null && denominator[1] !== null && denominator[1] !== 0 ? numerator[1] / denominator[1] : null
    return [numerator[0] / denominator[0], previous]
}

export const VISITORS_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'visitors',
    title: 'Visitors',
    tooltip: 'People with a pageview or screenview in the selected date range.',
    value: (row) => row.visitors ?? null,
    exportLabel: 'Visitors',
}

export const VIEWS_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'views',
    title: 'Pageviews',
    shortTitle: 'Views',
    value: (row) => row.views ?? null,
    exportLabel: 'Pageviews',
}

export const SESSIONS_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'sessions',
    title: 'Sessions',
    value: (row) => row.sessions ?? null,
    exportLabel: 'Sessions',
}

export const SESSIONS_PER_VISITOR_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'sessions_per_visitor',
    title: 'Sessions per visitor',
    shortTitle: 'Sessions/visitor',
    tooltip: 'Sessions divided by visitors.',
    value: (row) => ratio(row.sessions, row.visitors),
    kind: 'decimal',
    exportLabel: 'Sessions per visitor',
    exportValue: (value) => value.toFixed(2),
}

export const SESSION_DURATION_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'session_duration',
    title: 'Avg. session duration',
    shortTitle: 'Duration',
    tooltip: 'The average length of sessions that started here.',
    value: (row) => row.session_duration ?? null,
    kind: 'duration',
    exportLabel: 'Avg. session duration',
    exportValue: (value) => humanFriendlyDuration(value) ?? String(value),
}

export const PAGES_PER_SESSION_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'pages_per_session',
    title: 'Pages per session',
    shortTitle: 'Pages/session',
    tooltip: 'Pageviews divided by sessions.',
    value: (row) => ratio(row.views, row.sessions),
    kind: 'decimal',
    exportLabel: 'Pages per session',
    exportValue: (value) => value.toFixed(2),
}

export const PAGES_PER_VISITOR_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'pages_per_visitor',
    title: 'Pageviews per visitor',
    shortTitle: 'Views/visitor',
    tooltip: 'Pageviews divided by visitors.',
    value: (row) => ratio(row.views, row.visitors),
    kind: 'decimal',
    exportLabel: 'Pageviews per visitor',
    exportValue: (value) => value.toFixed(2),
}

export const BOUNCE_RATE_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'bounce_rate',
    title: 'Bounce rate',
    shortTitle: 'Bounce',
    tooltip: 'Sessions that left without a second pageview or any meaningful interaction.',
    value: (row) => row.bounce_rate ?? null,
    kind: 'percentage',
    reverseColors: true,
    exportLabel: 'Bounce rate',
}

export const CONVERSIONS_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'total_conversions',
    title: 'Conversions',
    value: (row) => row.total_conversions ?? null,
    exportLabel: 'Conversions',
}

export const CONVERSION_RATE_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'conversion_rate',
    title: 'Conversion rate',
    shortTitle: 'Conv. rate',
    tooltip: 'People who completed the goal, divided by visitors.',
    value: (row) => row.conversion_rate ?? null,
    kind: 'percentage',
    exportLabel: 'Conversion rate',
}

export const CONVERSION_VALUE_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'conversion_value',
    title: 'Conversion value',
    shortTitle: 'Value',
    tooltip: "The goal's value property, summed over the conversions of sessions that started here.",
    value: (row) => row.conversion_value ?? null,
    kind: 'currency',
    exportLabel: 'Conversion value',
    // A plain number, so a spreadsheet reads the export as money rather than as text.
    exportValue: (value) => value.toFixed(2),
}

export const AVG_CONVERSION_VALUE_COLUMN: BreakdownTableColumn<WebStatsRow> = {
    key: 'avg_conversion_value',
    title: 'Avg. conversion value',
    shortTitle: 'Avg. value',
    tooltip: "The goal's value property, averaged over the conversions of sessions that started here.",
    value: (row) => row.avg_conversion_value ?? null,
    kind: 'currency',
    exportLabel: 'Avg. conversion value',
    exportValue: (value) => value.toFixed(2),
}
