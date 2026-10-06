/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const BriefingSegmentApi = zod.object({
    text: zod.string().describe('A run of text in a paragraph. Includes its own spaces.'),
    item_key: zod.string().nullable().describe('Key of the item this run links to, or null for plain text.'),
    highlight: zod.boolean().describe('True only for the run that names the top item.'),
})

export type BriefingSegmentApi = zod.input<typeof BriefingSegmentApi>
export type BriefingSegmentApiOutput = zod.output<typeof BriefingSegmentApi>

export const PullRequestStateEnumApi = zod
    .enum(['draft', 'open', 'closed', 'merged'])
    .describe('\* `draft` - draft\n\* `open` - open\n\* `closed` - closed\n\* `merged` - merged')

export type PullRequestStateEnumApi = zod.input<typeof PullRequestStateEnumApi>
export type PullRequestStateEnumApiOutput = zod.output<typeof PullRequestStateEnumApi>

export const ReportMetricKindEnumApi = zod
    .enum([
        'affected_users',
        'affected_sessions',
        'occurrences',
        'conversion_rate',
        'error_rate',
        'duration',
        'revenue',
        'custom',
    ])
    .describe(
        '\* `affected_users` - affected_users\n\* `affected_sessions` - affected_sessions\n\* `occurrences` - occurrences\n\* `conversion_rate` - conversion_rate\n\* `error_rate` - error_rate\n\* `duration` - duration\n\* `revenue` - revenue\n\* `custom` - custom'
    )

export type ReportMetricKindEnumApi = zod.input<typeof ReportMetricKindEnumApi>
export type ReportMetricKindEnumApiOutput = zod.output<typeof ReportMetricKindEnumApi>

export const RoleEnumApi = zod
    .enum(['primary', 'supporting'])
    .describe('\* `primary` - primary\n\* `supporting` - supporting')

export type RoleEnumApi = zod.input<typeof RoleEnumApi>
export type RoleEnumApiOutput = zod.output<typeof RoleEnumApi>

export const ValueFormatEnumApi = zod
    .enum(['number', 'count', 'percentage', 'percentage_scaled', 'duration', 'currency'])
    .describe(
        '\* `number` - number\n\* `count` - count\n\* `percentage` - percentage\n\* `percentage_scaled` - percentage_scaled\n\* `duration` - duration\n\* `currency` - currency'
    )

export type ValueFormatEnumApi = zod.input<typeof ValueFormatEnumApi>
export type ValueFormatEnumApiOutput = zod.output<typeof ValueFormatEnumApi>

export const BriefingItemMetricApi = zod.object({
    metric_id: zod.string().describe('Stable slug of the metric within its report.'),
    title: zod.string().describe('Short label of what the metric measures.'),
    kind: zod
        .enum([
            'affected_users',
            'affected_sessions',
            'occurrences',
            'conversion_rate',
            'error_rate',
            'duration',
            'revenue',
            'custom',
        ])
        .describe(
            '\* `affected_users` - affected_users\n\* `affected_sessions` - affected_sessions\n\* `occurrences` - occurrences\n\* `conversion_rate` - conversion_rate\n\* `error_rate` - error_rate\n\* `duration` - duration\n\* `revenue` - revenue\n\* `custom` - custom'
        )
        .describe(
            'What the value measures, for example affected_users.\n\n\* `affected_users` - affected_users\n\* `affected_sessions` - affected_sessions\n\* `occurrences` - occurrences\n\* `conversion_rate` - conversion_rate\n\* `error_rate` - error_rate\n\* `duration` - duration\n\* `revenue` - revenue\n\* `custom` - custom'
        ),
    role: zod
        .enum(['primary', 'supporting'])
        .describe('\* `primary` - primary\n\* `supporting` - supporting')
        .describe(
            "`primary` for the report's key observation, otherwise `supporting`.\n\n\* `primary` - primary\n\* `supporting` - supporting"
        ),
    value: zod.number().describe('The latest saved snapshot of the metric.'),
    series: zod
        .array(zod.number())
        .nullable()
        .describe('Trailing per-bucket values saved with the snapshot, oldest first. Null when none were saved.'),
    value_format: zod
        .enum(['number', 'count', 'percentage', 'percentage_scaled', 'duration', 'currency'])
        .describe(
            '\* `number` - number\n\* `count` - count\n\* `percentage` - percentage\n\* `percentage_scaled` - percentage_scaled\n\* `duration` - duration\n\* `currency` - currency'
        )
        .describe(
            'How to format the value, for example count.\n\n\* `number` - number\n\* `count` - count\n\* `percentage` - percentage\n\* `percentage_scaled` - percentage_scaled\n\* `duration` - duration\n\* `currency` - currency'
        ),
    unit: zod.string().nullable().describe('Optional short suffix or currency code, such as USD.'),
    query: zod
        .unknown()
        .describe("The metric's live InsightVizNode wrapping one TrendsQuery, as the report stores it."),
})

export type BriefingItemMetricApi = zod.input<typeof BriefingItemMetricApi>
export type BriefingItemMetricApiOutput = zod.output<typeof BriefingItemMetricApi>

export const BriefingItemChartApi = zod.object({
    chart_id: zod.string().describe('Stable slug of the chart within its report.'),
    title: zod.string().describe('Short heading of the chart.'),
    query: zod.unknown().describe('The query node the report body draws, as the report stores it.'),
})

export type BriefingItemChartApi = zod.input<typeof BriefingItemChartApi>
export type BriefingItemChartApiOutput = zod.output<typeof BriefingItemChartApi>

export const BriefingItemReportApi = zod.object({
    priority: zod.string().nullable().describe("The report's priority, P0 to P4, or null if unset."),
    summary: zod.string().describe("The report's summary, shortened to a few sentences."),
    pull_request_state: zod
        .union([
            zod
                .enum(['draft', 'open', 'closed', 'merged'])
                .describe('\* `draft` - draft\n\* `open` - open\n\* `closed` - closed\n\* `merged` - merged'),
            zod.null(),
        ])
        .describe(
            "State of the report's implementation pull request, or null when it has none.\n\n\* `draft` - draft\n\* `open` - open\n\* `closed` - closed\n\* `merged` - merged"
        ),
    pull_request_url: zod
        .string()
        .nullable()
        .describe("URL of the report's implementation pull request, or null when it has none."),
    signal_count: zod.number().describe('How many signals the report groups.'),
    updated_at: zod.iso.datetime({ offset: true }).describe('When the report last changed.'),
    metrics: zod
        .array(
            zod.object({
                metric_id: zod.string().describe('Stable slug of the metric within its report.'),
                title: zod.string().describe('Short label of what the metric measures.'),
                kind: zod
                    .enum([
                        'affected_users',
                        'affected_sessions',
                        'occurrences',
                        'conversion_rate',
                        'error_rate',
                        'duration',
                        'revenue',
                        'custom',
                    ])
                    .describe(
                        '\* `affected_users` - affected_users\n\* `affected_sessions` - affected_sessions\n\* `occurrences` - occurrences\n\* `conversion_rate` - conversion_rate\n\* `error_rate` - error_rate\n\* `duration` - duration\n\* `revenue` - revenue\n\* `custom` - custom'
                    )
                    .describe(
                        'What the value measures, for example affected_users.\n\n\* `affected_users` - affected_users\n\* `affected_sessions` - affected_sessions\n\* `occurrences` - occurrences\n\* `conversion_rate` - conversion_rate\n\* `error_rate` - error_rate\n\* `duration` - duration\n\* `revenue` - revenue\n\* `custom` - custom'
                    ),
                role: zod
                    .enum(['primary', 'supporting'])
                    .describe('\* `primary` - primary\n\* `supporting` - supporting')
                    .describe(
                        "`primary` for the report's key observation, otherwise `supporting`.\n\n\* `primary` - primary\n\* `supporting` - supporting"
                    ),
                value: zod.number().describe('The latest saved snapshot of the metric.'),
                series: zod
                    .array(zod.number())
                    .nullable()
                    .describe(
                        'Trailing per-bucket values saved with the snapshot, oldest first. Null when none were saved.'
                    ),
                value_format: zod
                    .enum(['number', 'count', 'percentage', 'percentage_scaled', 'duration', 'currency'])
                    .describe(
                        '\* `number` - number\n\* `count` - count\n\* `percentage` - percentage\n\* `percentage_scaled` - percentage_scaled\n\* `duration` - duration\n\* `currency` - currency'
                    )
                    .describe(
                        'How to format the value, for example count.\n\n\* `number` - number\n\* `count` - count\n\* `percentage` - percentage\n\* `percentage_scaled` - percentage_scaled\n\* `duration` - duration\n\* `currency` - currency'
                    ),
                unit: zod.string().nullable().describe('Optional short suffix or currency code, such as USD.'),
                query: zod
                    .unknown()
                    .describe("The metric's live InsightVizNode wrapping one TrendsQuery, as the report stores it."),
            })
        )
        .describe("The report's metrics that have a saved snapshot, in the report's order."),
    charts: zod
        .array(
            zod.object({
                chart_id: zod.string().describe('Stable slug of the chart within its report.'),
                title: zod.string().describe('Short heading of the chart.'),
                query: zod.unknown().describe('The query node the report body draws, as the report stores it.'),
            })
        )
        .describe("The charts in the report body, in the report's order."),
})

export type BriefingItemReportApi = zod.input<typeof BriefingItemReportApi>
export type BriefingItemReportApiOutput = zod.output<typeof BriefingItemReportApi>

export const TodayItemGroupEnumApi = zod
    .enum(['report', 'dashboard', 'other'])
    .describe('\* `report` - REPORT\n\* `dashboard` - DASHBOARD\n\* `other` - OTHER')

export type TodayItemGroupEnumApi = zod.input<typeof TodayItemGroupEnumApi>
export type TodayItemGroupEnumApiOutput = zod.output<typeof TodayItemGroupEnumApi>

export const TodayItemSourceEnumApi = zod
    .enum(['self_driving', 'product_analytics', 'alerts', 'support', 'error_tracking', 'github'])
    .describe(
        '\* `self_driving` - SELF_DRIVING\n\* `product_analytics` - PRODUCT_ANALYTICS\n\* `alerts` - ALERTS\n\* `support` - SUPPORT\n\* `error_tracking` - ERROR_TRACKING\n\* `github` - GITHUB'
    )

export type TodayItemSourceEnumApi = zod.input<typeof TodayItemSourceEnumApi>
export type TodayItemSourceEnumApiOutput = zod.output<typeof TodayItemSourceEnumApi>

export const TodayItemReasonEnumApi = zod
    .enum([
        'claimed_by_you',
        'waiting_for_you',
        'suggested_reviewer',
        'urgent_for_project',
        'dashboard_you_viewed',
        'dashboard_you_starred',
        'insight_you_viewed',
        'insight_you_starred',
        'alert_firing',
        'assigned_ticket',
        'assigned_error_issue',
        'review_requested',
        'your_pull_request',
    ])
    .describe(
        '\* `claimed_by_you` - CLAIMED_BY_YOU\n\* `waiting_for_you` - WAITING_FOR_YOU\n\* `suggested_reviewer` - SUGGESTED_REVIEWER\n\* `urgent_for_project` - URGENT_FOR_PROJECT\n\* `dashboard_you_viewed` - DASHBOARD_YOU_VIEWED\n\* `dashboard_you_starred` - DASHBOARD_YOU_STARRED\n\* `insight_you_viewed` - INSIGHT_YOU_VIEWED\n\* `insight_you_starred` - INSIGHT_YOU_STARRED\n\* `alert_firing` - ALERT_FIRING\n\* `assigned_ticket` - ASSIGNED_TICKET\n\* `assigned_error_issue` - ASSIGNED_ERROR_ISSUE\n\* `review_requested` - REVIEW_REQUESTED\n\* `your_pull_request` - YOUR_PULL_REQUEST'
    )

export type TodayItemReasonEnumApi = zod.input<typeof TodayItemReasonEnumApi>
export type TodayItemReasonEnumApiOutput = zod.output<typeof TodayItemReasonEnumApi>

export const BriefingItemStateEnumApi = zod
    .enum(['open', 'done', 'dismissed'])
    .describe('\* `open` - OPEN\n\* `done` - DONE\n\* `dismissed` - DISMISSED')

export type BriefingItemStateEnumApi = zod.input<typeof BriefingItemStateEnumApi>
export type BriefingItemStateEnumApiOutput = zod.output<typeof BriefingItemStateEnumApi>

export const BriefingItemApi = zod.object({
    key: zod.string().describe('Stable item key, for example report:<uuid>, dashboard:<id> or ticket:<uuid>.'),
    title: zod.string().describe("The item's own title, as the source names it."),
    label: zod.string().describe('Short left-bar label of at most 6 words.'),
    signal: zod.string().describe("Short fact under the label, at most 40 characters, for example 'Spend down 37%'."),
    url: zod.string().describe('Where the item opens: an app path, or a GitHub URL for pull requests.'),
    rank: zod.number().describe('Position in the briefing, 1 is the top item.'),
    source_product: zod
        .string()
        .nullable()
        .describe(
            'For a report, the product its signals came from, for example error_tracking or session_replay. Null for every other item.'
        ),
    report: zod
        .union([
            zod.object({
                priority: zod.string().nullable().describe("The report's priority, P0 to P4, or null if unset."),
                summary: zod.string().describe("The report's summary, shortened to a few sentences."),
                pull_request_state: zod
                    .union([
                        zod
                            .enum(['draft', 'open', 'closed', 'merged'])
                            .describe(
                                '\* `draft` - draft\n\* `open` - open\n\* `closed` - closed\n\* `merged` - merged'
                            ),
                        zod.null(),
                    ])
                    .describe(
                        "State of the report's implementation pull request, or null when it has none.\n\n\* `draft` - draft\n\* `open` - open\n\* `closed` - closed\n\* `merged` - merged"
                    ),
                pull_request_url: zod
                    .string()
                    .nullable()
                    .describe("URL of the report's implementation pull request, or null when it has none."),
                signal_count: zod.number().describe('How many signals the report groups.'),
                updated_at: zod.iso.datetime({ offset: true }).describe('When the report last changed.'),
                metrics: zod
                    .array(
                        zod.object({
                            metric_id: zod.string().describe('Stable slug of the metric within its report.'),
                            title: zod.string().describe('Short label of what the metric measures.'),
                            kind: zod
                                .enum([
                                    'affected_users',
                                    'affected_sessions',
                                    'occurrences',
                                    'conversion_rate',
                                    'error_rate',
                                    'duration',
                                    'revenue',
                                    'custom',
                                ])
                                .describe(
                                    '\* `affected_users` - affected_users\n\* `affected_sessions` - affected_sessions\n\* `occurrences` - occurrences\n\* `conversion_rate` - conversion_rate\n\* `error_rate` - error_rate\n\* `duration` - duration\n\* `revenue` - revenue\n\* `custom` - custom'
                                )
                                .describe(
                                    'What the value measures, for example affected_users.\n\n\* `affected_users` - affected_users\n\* `affected_sessions` - affected_sessions\n\* `occurrences` - occurrences\n\* `conversion_rate` - conversion_rate\n\* `error_rate` - error_rate\n\* `duration` - duration\n\* `revenue` - revenue\n\* `custom` - custom'
                                ),
                            role: zod
                                .enum(['primary', 'supporting'])
                                .describe('\* `primary` - primary\n\* `supporting` - supporting')
                                .describe(
                                    "`primary` for the report's key observation, otherwise `supporting`.\n\n\* `primary` - primary\n\* `supporting` - supporting"
                                ),
                            value: zod.number().describe('The latest saved snapshot of the metric.'),
                            series: zod
                                .array(zod.number())
                                .nullable()
                                .describe(
                                    'Trailing per-bucket values saved with the snapshot, oldest first. Null when none were saved.'
                                ),
                            value_format: zod
                                .enum(['number', 'count', 'percentage', 'percentage_scaled', 'duration', 'currency'])
                                .describe(
                                    '\* `number` - number\n\* `count` - count\n\* `percentage` - percentage\n\* `percentage_scaled` - percentage_scaled\n\* `duration` - duration\n\* `currency` - currency'
                                )
                                .describe(
                                    'How to format the value, for example count.\n\n\* `number` - number\n\* `count` - count\n\* `percentage` - percentage\n\* `percentage_scaled` - percentage_scaled\n\* `duration` - duration\n\* `currency` - currency'
                                ),
                            unit: zod
                                .string()
                                .nullable()
                                .describe('Optional short suffix or currency code, such as USD.'),
                            query: zod
                                .unknown()
                                .describe(
                                    "The metric's live InsightVizNode wrapping one TrendsQuery, as the report stores it."
                                ),
                        })
                    )
                    .describe("The report's metrics that have a saved snapshot, in the report's order."),
                charts: zod
                    .array(
                        zod.object({
                            chart_id: zod.string().describe('Stable slug of the chart within its report.'),
                            title: zod.string().describe('Short heading of the chart.'),
                            query: zod
                                .unknown()
                                .describe('The query node the report body draws, as the report stores it.'),
                        })
                    )
                    .describe("The charts in the report body, in the report's order."),
            }),
            zod.null(),
        ])
        .describe(
            'For a report, its priority, summary, implementation pull request and the metric snapshots the viewer may read. Null for every other item and for a deleted report.'
        ),
    group: zod
        .enum(['report', 'dashboard', 'other'])
        .describe('\* `report` - REPORT\n\* `dashboard` - DASHBOARD\n\* `other` - OTHER'),
    source: zod
        .enum(['self_driving', 'product_analytics', 'alerts', 'support', 'error_tracking', 'github'])
        .describe(
            '\* `self_driving` - SELF_DRIVING\n\* `product_analytics` - PRODUCT_ANALYTICS\n\* `alerts` - ALERTS\n\* `support` - SUPPORT\n\* `error_tracking` - ERROR_TRACKING\n\* `github` - GITHUB'
        ),
    reason: zod
        .enum([
            'claimed_by_you',
            'waiting_for_you',
            'suggested_reviewer',
            'urgent_for_project',
            'dashboard_you_viewed',
            'dashboard_you_starred',
            'insight_you_viewed',
            'insight_you_starred',
            'alert_firing',
            'assigned_ticket',
            'assigned_error_issue',
            'review_requested',
            'your_pull_request',
        ])
        .describe(
            '\* `claimed_by_you` - CLAIMED_BY_YOU\n\* `waiting_for_you` - WAITING_FOR_YOU\n\* `suggested_reviewer` - SUGGESTED_REVIEWER\n\* `urgent_for_project` - URGENT_FOR_PROJECT\n\* `dashboard_you_viewed` - DASHBOARD_YOU_VIEWED\n\* `dashboard_you_starred` - DASHBOARD_YOU_STARRED\n\* `insight_you_viewed` - INSIGHT_YOU_VIEWED\n\* `insight_you_starred` - INSIGHT_YOU_STARRED\n\* `alert_firing` - ALERT_FIRING\n\* `assigned_ticket` - ASSIGNED_TICKET\n\* `assigned_error_issue` - ASSIGNED_ERROR_ISSUE\n\* `review_requested` - REVIEW_REQUESTED\n\* `your_pull_request` - YOUR_PULL_REQUEST'
        ),
    state: zod
        .enum(['open', 'done', 'dismissed'])
        .describe('\* `open` - OPEN\n\* `done` - DONE\n\* `dismissed` - DISMISSED')
        .describe(
            '`done` when the item was resolved since the briefing was written, `dismissed` when it was dismissed or suppressed, else `open`. Pull requests always stay `open`.\n\n\* `open` - OPEN\n\* `done` - DONE\n\* `dismissed` - DISMISSED'
        ),
})

export type BriefingItemApi = zod.input<typeof BriefingItemApi>
export type BriefingItemApiOutput = zod.output<typeof BriefingItemApi>

export const BriefingStatusEnumApi = zod
    .enum(['collecting', 'writing', 'ready', 'failed'])
    .describe('\* `collecting` - COLLECTING\n\* `writing` - WRITING\n\* `ready` - READY\n\* `failed` - FAILED')

export type BriefingStatusEnumApi = zod.input<typeof BriefingStatusEnumApi>
export type BriefingStatusEnumApiOutput = zod.output<typeof BriefingStatusEnumApi>

export const WriterEnumApi = zod.enum(['agent']).describe('\* `agent` - AGENT')

export type WriterEnumApi = zod.input<typeof WriterEnumApi>
export type WriterEnumApiOutput = zod.output<typeof WriterEnumApi>

export const BriefingApi = zod.object({
    id: zod.string().describe('Briefing id.'),
    local_day: zod.iso.date().describe("The day this briefing is for, in the person's timezone."),
    headline: zod.string().describe('One sentence that counts what needs the person.'),
    paragraphs: zod
        .array(
            zod.array(
                zod.object({
                    text: zod.string().describe('A run of text in a paragraph. Includes its own spaces.'),
                    item_key: zod
                        .string()
                        .nullable()
                        .describe('Key of the item this run links to, or null for plain text.'),
                    highlight: zod.boolean().describe('True only for the run that names the top item.'),
                })
            )
        )
        .describe('Up to 3 paragraphs, each a list of text runs; runs with an item_key are links.'),
    items: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .describe('Stable item key, for example report:<uuid>, dashboard:<id> or ticket:<uuid>.'),
                title: zod.string().describe("The item's own title, as the source names it."),
                label: zod.string().describe('Short left-bar label of at most 6 words.'),
                signal: zod
                    .string()
                    .describe("Short fact under the label, at most 40 characters, for example 'Spend down 37%'."),
                url: zod.string().describe('Where the item opens: an app path, or a GitHub URL for pull requests.'),
                rank: zod.number().describe('Position in the briefing, 1 is the top item.'),
                source_product: zod
                    .string()
                    .nullable()
                    .describe(
                        'For a report, the product its signals came from, for example error_tracking or session_replay. Null for every other item.'
                    ),
                report: zod
                    .union([
                        zod.object({
                            priority: zod
                                .string()
                                .nullable()
                                .describe("The report's priority, P0 to P4, or null if unset."),
                            summary: zod.string().describe("The report's summary, shortened to a few sentences."),
                            pull_request_state: zod
                                .union([
                                    zod
                                        .enum(['draft', 'open', 'closed', 'merged'])
                                        .describe(
                                            '\* `draft` - draft\n\* `open` - open\n\* `closed` - closed\n\* `merged` - merged'
                                        ),
                                    zod.null(),
                                ])
                                .describe(
                                    "State of the report's implementation pull request, or null when it has none.\n\n\* `draft` - draft\n\* `open` - open\n\* `closed` - closed\n\* `merged` - merged"
                                ),
                            pull_request_url: zod
                                .string()
                                .nullable()
                                .describe("URL of the report's implementation pull request, or null when it has none."),
                            signal_count: zod.number().describe('How many signals the report groups.'),
                            updated_at: zod.iso.datetime({ offset: true }).describe('When the report last changed.'),
                            metrics: zod
                                .array(
                                    zod.object({
                                        metric_id: zod
                                            .string()
                                            .describe('Stable slug of the metric within its report.'),
                                        title: zod.string().describe('Short label of what the metric measures.'),
                                        kind: zod
                                            .enum([
                                                'affected_users',
                                                'affected_sessions',
                                                'occurrences',
                                                'conversion_rate',
                                                'error_rate',
                                                'duration',
                                                'revenue',
                                                'custom',
                                            ])
                                            .describe(
                                                '\* `affected_users` - affected_users\n\* `affected_sessions` - affected_sessions\n\* `occurrences` - occurrences\n\* `conversion_rate` - conversion_rate\n\* `error_rate` - error_rate\n\* `duration` - duration\n\* `revenue` - revenue\n\* `custom` - custom'
                                            )
                                            .describe(
                                                'What the value measures, for example affected_users.\n\n\* `affected_users` - affected_users\n\* `affected_sessions` - affected_sessions\n\* `occurrences` - occurrences\n\* `conversion_rate` - conversion_rate\n\* `error_rate` - error_rate\n\* `duration` - duration\n\* `revenue` - revenue\n\* `custom` - custom'
                                            ),
                                        role: zod
                                            .enum(['primary', 'supporting'])
                                            .describe('\* `primary` - primary\n\* `supporting` - supporting')
                                            .describe(
                                                "`primary` for the report's key observation, otherwise `supporting`.\n\n\* `primary` - primary\n\* `supporting` - supporting"
                                            ),
                                        value: zod.number().describe('The latest saved snapshot of the metric.'),
                                        series: zod
                                            .array(zod.number())
                                            .nullable()
                                            .describe(
                                                'Trailing per-bucket values saved with the snapshot, oldest first. Null when none were saved.'
                                            ),
                                        value_format: zod
                                            .enum([
                                                'number',
                                                'count',
                                                'percentage',
                                                'percentage_scaled',
                                                'duration',
                                                'currency',
                                            ])
                                            .describe(
                                                '\* `number` - number\n\* `count` - count\n\* `percentage` - percentage\n\* `percentage_scaled` - percentage_scaled\n\* `duration` - duration\n\* `currency` - currency'
                                            )
                                            .describe(
                                                'How to format the value, for example count.\n\n\* `number` - number\n\* `count` - count\n\* `percentage` - percentage\n\* `percentage_scaled` - percentage_scaled\n\* `duration` - duration\n\* `currency` - currency'
                                            ),
                                        unit: zod
                                            .string()
                                            .nullable()
                                            .describe('Optional short suffix or currency code, such as USD.'),
                                        query: zod
                                            .unknown()
                                            .describe(
                                                "The metric's live InsightVizNode wrapping one TrendsQuery, as the report stores it."
                                            ),
                                    })
                                )
                                .describe("The report's metrics that have a saved snapshot, in the report's order."),
                            charts: zod
                                .array(
                                    zod.object({
                                        chart_id: zod.string().describe('Stable slug of the chart within its report.'),
                                        title: zod.string().describe('Short heading of the chart.'),
                                        query: zod
                                            .unknown()
                                            .describe('The query node the report body draws, as the report stores it.'),
                                    })
                                )
                                .describe("The charts in the report body, in the report's order."),
                        }),
                        zod.null(),
                    ])
                    .describe(
                        'For a report, its priority, summary, implementation pull request and the metric snapshots the viewer may read. Null for every other item and for a deleted report.'
                    ),
                group: zod
                    .enum(['report', 'dashboard', 'other'])
                    .describe('\* `report` - REPORT\n\* `dashboard` - DASHBOARD\n\* `other` - OTHER'),
                source: zod
                    .enum(['self_driving', 'product_analytics', 'alerts', 'support', 'error_tracking', 'github'])
                    .describe(
                        '\* `self_driving` - SELF_DRIVING\n\* `product_analytics` - PRODUCT_ANALYTICS\n\* `alerts` - ALERTS\n\* `support` - SUPPORT\n\* `error_tracking` - ERROR_TRACKING\n\* `github` - GITHUB'
                    ),
                reason: zod
                    .enum([
                        'claimed_by_you',
                        'waiting_for_you',
                        'suggested_reviewer',
                        'urgent_for_project',
                        'dashboard_you_viewed',
                        'dashboard_you_starred',
                        'insight_you_viewed',
                        'insight_you_starred',
                        'alert_firing',
                        'assigned_ticket',
                        'assigned_error_issue',
                        'review_requested',
                        'your_pull_request',
                    ])
                    .describe(
                        '\* `claimed_by_you` - CLAIMED_BY_YOU\n\* `waiting_for_you` - WAITING_FOR_YOU\n\* `suggested_reviewer` - SUGGESTED_REVIEWER\n\* `urgent_for_project` - URGENT_FOR_PROJECT\n\* `dashboard_you_viewed` - DASHBOARD_YOU_VIEWED\n\* `dashboard_you_starred` - DASHBOARD_YOU_STARRED\n\* `insight_you_viewed` - INSIGHT_YOU_VIEWED\n\* `insight_you_starred` - INSIGHT_YOU_STARRED\n\* `alert_firing` - ALERT_FIRING\n\* `assigned_ticket` - ASSIGNED_TICKET\n\* `assigned_error_issue` - ASSIGNED_ERROR_ISSUE\n\* `review_requested` - REVIEW_REQUESTED\n\* `your_pull_request` - YOUR_PULL_REQUEST'
                    ),
                state: zod
                    .enum(['open', 'done', 'dismissed'])
                    .describe('\* `open` - OPEN\n\* `done` - DONE\n\* `dismissed` - DISMISSED')
                    .describe(
                        '`done` when the item was resolved since the briefing was written, `dismissed` when it was dismissed or suppressed, else `open`. Pull requests always stay `open`.\n\n\* `open` - OPEN\n\* `done` - DONE\n\* `dismissed` - DISMISSED'
                    ),
            })
        )
        .describe('The items the text names, in rank order: what the page and the left bar show.'),
    more_reports_count: zod.number().describe('Other open reports for the person, beyond the ones the briefing shows.'),
    open_reports_count: zod
        .number()
        .describe('Open reports in the whole project beyond the ones the briefing shows, whoever they are for.'),
    status: zod
        .enum(['collecting', 'writing', 'ready', 'failed'])
        .describe('\* `collecting` - COLLECTING\n\* `writing` - WRITING\n\* `ready` - READY\n\* `failed` - FAILED'),
    writer: zod.union([zod.enum(['agent']).describe('\* `agent` - AGENT'), zod.null()]),
    created_at: zod.iso.datetime({ offset: true }),
    ready_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type BriefingApi = zod.input<typeof BriefingApi>
export type BriefingApiOutput = zod.output<typeof BriefingApi>

export const CandidateFactApi = zod.object({
    name: zod.string().describe('Fact name, for example pct_change or unread_messages.'),
    value: zod.string().describe('Fact value as text.'),
})

export type CandidateFactApi = zod.input<typeof CandidateFactApi>
export type CandidateFactApiOutput = zod.output<typeof CandidateFactApi>

export const CandidateApi = zod.object({
    key: zod.string().describe('Stable item key, for example report:<uuid> or dashboard:<id>.'),
    title: zod.string().describe("The item's own title."),
    url: zod.string().describe('Where the item opens.'),
    rank: zod.number().describe('Position in the briefing, 1 is the top item.'),
    facts: zod
        .array(
            zod.object({
                name: zod.string().describe('Fact name, for example pct_change or unread_messages.'),
                value: zod.string().describe('Fact value as text.'),
            })
        )
        .describe('The numbers and short facts the briefing text rests on.'),
    group: zod
        .enum(['report', 'dashboard', 'other'])
        .describe('\* `report` - REPORT\n\* `dashboard` - DASHBOARD\n\* `other` - OTHER'),
    source: zod
        .enum(['self_driving', 'product_analytics', 'alerts', 'support', 'error_tracking', 'github'])
        .describe(
            '\* `self_driving` - SELF_DRIVING\n\* `product_analytics` - PRODUCT_ANALYTICS\n\* `alerts` - ALERTS\n\* `support` - SUPPORT\n\* `error_tracking` - ERROR_TRACKING\n\* `github` - GITHUB'
        ),
    reason: zod
        .enum([
            'claimed_by_you',
            'waiting_for_you',
            'suggested_reviewer',
            'urgent_for_project',
            'dashboard_you_viewed',
            'dashboard_you_starred',
            'insight_you_viewed',
            'insight_you_starred',
            'alert_firing',
            'assigned_ticket',
            'assigned_error_issue',
            'review_requested',
            'your_pull_request',
        ])
        .describe(
            '\* `claimed_by_you` - CLAIMED_BY_YOU\n\* `waiting_for_you` - WAITING_FOR_YOU\n\* `suggested_reviewer` - SUGGESTED_REVIEWER\n\* `urgent_for_project` - URGENT_FOR_PROJECT\n\* `dashboard_you_viewed` - DASHBOARD_YOU_VIEWED\n\* `dashboard_you_starred` - DASHBOARD_YOU_STARRED\n\* `insight_you_viewed` - INSIGHT_YOU_VIEWED\n\* `insight_you_starred` - INSIGHT_YOU_STARRED\n\* `alert_firing` - ALERT_FIRING\n\* `assigned_ticket` - ASSIGNED_TICKET\n\* `assigned_error_issue` - ASSIGNED_ERROR_ISSUE\n\* `review_requested` - REVIEW_REQUESTED\n\* `your_pull_request` - YOUR_PULL_REQUEST'
        ),
})

export type CandidateApi = zod.input<typeof CandidateApi>
export type CandidateApiOutput = zod.output<typeof CandidateApi>

export const CandidateListApi = zod.object({
    local_day: zod.iso.date().describe("The day the list is for, in the person's timezone."),
    candidates: zod
        .array(
            zod.object({
                key: zod.string().describe('Stable item key, for example report:<uuid> or dashboard:<id>.'),
                title: zod.string().describe("The item's own title."),
                url: zod.string().describe('Where the item opens.'),
                rank: zod.number().describe('Position in the briefing, 1 is the top item.'),
                facts: zod
                    .array(
                        zod.object({
                            name: zod.string().describe('Fact name, for example pct_change or unread_messages.'),
                            value: zod.string().describe('Fact value as text.'),
                        })
                    )
                    .describe('The numbers and short facts the briefing text rests on.'),
                group: zod
                    .enum(['report', 'dashboard', 'other'])
                    .describe('\* `report` - REPORT\n\* `dashboard` - DASHBOARD\n\* `other` - OTHER'),
                source: zod
                    .enum(['self_driving', 'product_analytics', 'alerts', 'support', 'error_tracking', 'github'])
                    .describe(
                        '\* `self_driving` - SELF_DRIVING\n\* `product_analytics` - PRODUCT_ANALYTICS\n\* `alerts` - ALERTS\n\* `support` - SUPPORT\n\* `error_tracking` - ERROR_TRACKING\n\* `github` - GITHUB'
                    ),
                reason: zod
                    .enum([
                        'claimed_by_you',
                        'waiting_for_you',
                        'suggested_reviewer',
                        'urgent_for_project',
                        'dashboard_you_viewed',
                        'dashboard_you_starred',
                        'insight_you_viewed',
                        'insight_you_starred',
                        'alert_firing',
                        'assigned_ticket',
                        'assigned_error_issue',
                        'review_requested',
                        'your_pull_request',
                    ])
                    .describe(
                        '\* `claimed_by_you` - CLAIMED_BY_YOU\n\* `waiting_for_you` - WAITING_FOR_YOU\n\* `suggested_reviewer` - SUGGESTED_REVIEWER\n\* `urgent_for_project` - URGENT_FOR_PROJECT\n\* `dashboard_you_viewed` - DASHBOARD_YOU_VIEWED\n\* `dashboard_you_starred` - DASHBOARD_YOU_STARRED\n\* `insight_you_viewed` - INSIGHT_YOU_VIEWED\n\* `insight_you_starred` - INSIGHT_YOU_STARRED\n\* `alert_firing` - ALERT_FIRING\n\* `assigned_ticket` - ASSIGNED_TICKET\n\* `assigned_error_issue` - ASSIGNED_ERROR_ISSUE\n\* `review_requested` - REVIEW_REQUESTED\n\* `your_pull_request` - YOUR_PULL_REQUEST'
                    ),
            })
        )
        .describe("The briefing's items in rank order, up to 5."),
    more_reports_count: zod.number().describe('Other open reports for the person not in the list.'),
})

export type CandidateListApi = zod.input<typeof CandidateListApi>
export type CandidateListApiOutput = zod.output<typeof CandidateListApi>

export const PullRequestLinkApi = zod.object({
    url: zod.string().describe('The pull request on GitHub.'),
    number: zod.number().describe('The pull request number.'),
})

export type PullRequestLinkApi = zod.input<typeof PullRequestLinkApi>
export type PullRequestLinkApiOutput = zod.output<typeof PullRequestLinkApi>

export const CitedSourceEnumApi = zod.enum(['code', 'slack']).describe('\* `code` - Code\n\* `slack` - Slack')

export type CitedSourceEnumApi = zod.input<typeof CitedSourceEnumApi>
export type CitedSourceEnumApiOutput = zod.output<typeof CitedSourceEnumApi>

export const RecordingTargetApi = zod.object({
    session_id: zod.string().describe("The recording's session id."),
    start_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Where the player starts, a few seconds before the finding.'),
    offset: zod.string().nullable().describe("The finding's time in the recording, as MM:SS."),
    seek_seconds: zod
        .number()
        .nullable()
        .describe('Where the player starts, in seconds from the recording start. Null without an offset.'),
})

export type RecordingTargetApi = zod.input<typeof RecordingTargetApi>
export type RecordingTargetApiOutput = zod.output<typeof RecordingTargetApi>

export const PageLinkApi = zod.object({
    url: zod.string().describe('Where the link goes, outside PostHog.'),
    text: zod.string().describe('The link text.'),
})

export type PageLinkApi = zod.input<typeof PageLinkApi>
export type PageLinkApiOutput = zod.output<typeof PageLinkApi>

export const CodeFileApi = zod.object({
    repo: zod.string().describe('The repository as owner\/name.'),
    path: zod.string().describe('The file path in the repository.'),
})

export type CodeFileApi = zod.input<typeof CodeFileApi>
export type CodeFileApiOutput = zod.output<typeof CodeFileApi>

export const PreviewLineApi = zod.object({
    text: zod.string().describe('One line of the preview block.'),
    quiet: zod.boolean().describe('Whether the line is secondary, such as a stack frame.'),
})

export type PreviewLineApi = zod.input<typeof PreviewLineApi>
export type PreviewLineApiOutput = zod.output<typeof PreviewLineApi>

export const SignalPreviewApi = zod.object({
    hint: zod.string().describe("What expanding the signal shows, such as 'Show the stack trace'."),
    code: zod
        .array(
            zod.object({
                repo: zod.string().describe('The repository as owner\/name.'),
                path: zod.string().describe('The file path in the repository.'),
            })
        )
        .describe("Repository files to quote, the finding's own file first."),
    block: zod
        .array(
            zod.object({
                text: zod.string().describe('One line of the preview block.'),
                quiet: zod.boolean().describe('Whether the line is secondary, such as a stack frame.'),
            })
        )
        .describe('A preformatted block, such as a stack trace or a query.'),
    text: zod.string().describe("The finding's text beyond its first sentence."),
    facts: zod.array(zod.string()).describe('Short facts about the source.'),
    link: zod
        .union([
            zod.object({
                url: zod.string().describe('Where the link goes, outside PostHog.'),
                text: zod.string().describe('The link text.'),
            }),
            zod.null(),
        ])
        .describe("A link that replaces the signal's own destination."),
    link_label: zod.string().nullable().describe("A label that replaces the label of the signal's own destination."),
})

export type SignalPreviewApi = zod.input<typeof SignalPreviewApi>
export type SignalPreviewApiOutput = zod.output<typeof SignalPreviewApi>

export const SignalViewApi = zod.object({
    signal_id: zod.string().describe("The signal's id."),
    source_product: zod.string().describe('The product that emitted the signal.'),
    source_type: zod.string().describe('The kind of signal within its product.'),
    source_id: zod.string().describe('The id of the source object, such as an issue or a ticket.'),
    content: zod.string().describe("The signal's text as emitted."),
    timestamp: zod.iso.datetime({ offset: true }).describe('When the signal happened.'),
    extra: zod
        .record(zod.string(), zod.unknown())
        .describe(
            "The emitter's extra fields as it sent them, used to link to the source object. Values are any JSON."
        ),
    headline: zod.string().describe('The signal as one short line.'),
    lead: zod.string().describe("The signal's first sentence."),
    meta: zod.string().describe('Identifiers such as a pull request or ticket number, joined by dots.'),
    cited: zod
        .union([zod.enum(['code', 'slack']).describe('\* `code` - Code\n\* `slack` - Slack'), zod.null()])
        .describe('What a scout finding cites: code or a Slack thread.\n\n\* `code` - Code\n\* `slack` - Slack'),
    recording: zod
        .union([
            zod.object({
                session_id: zod.string().describe("The recording's session id."),
                start_at: zod.iso
                    .datetime({ offset: true })
                    .nullable()
                    .describe('Where the player starts, a few seconds before the finding.'),
                offset: zod.string().nullable().describe("The finding's time in the recording, as MM:SS."),
                seek_seconds: zod
                    .number()
                    .nullable()
                    .describe('Where the player starts, in seconds from the recording start. Null without an offset.'),
            }),
            zod.null(),
        ])
        .describe('The recording the signal plays, if any.'),
    link: zod
        .union([
            zod.object({
                url: zod.string().describe('Where the link goes, outside PostHog.'),
                text: zod.string().describe('The link text.'),
            }),
            zod.null(),
        ])
        .describe('Where a scout finding links outside PostHog, if anywhere.'),
    preview: zod
        .union([
            zod.object({
                hint: zod.string().describe("What expanding the signal shows, such as 'Show the stack trace'."),
                code: zod
                    .array(
                        zod.object({
                            repo: zod.string().describe('The repository as owner\/name.'),
                            path: zod.string().describe('The file path in the repository.'),
                        })
                    )
                    .describe("Repository files to quote, the finding's own file first."),
                block: zod
                    .array(
                        zod.object({
                            text: zod.string().describe('One line of the preview block.'),
                            quiet: zod.boolean().describe('Whether the line is secondary, such as a stack frame.'),
                        })
                    )
                    .describe('A preformatted block, such as a stack trace or a query.'),
                text: zod.string().describe("The finding's text beyond its first sentence."),
                facts: zod.array(zod.string()).describe('Short facts about the source.'),
                link: zod
                    .union([
                        zod.object({
                            url: zod.string().describe('Where the link goes, outside PostHog.'),
                            text: zod.string().describe('The link text.'),
                        }),
                        zod.null(),
                    ])
                    .describe("A link that replaces the signal's own destination."),
                link_label: zod
                    .string()
                    .nullable()
                    .describe("A label that replaces the label of the signal's own destination."),
            }),
            zod.null(),
        ])
        .describe('What expanding the signal shows, if anything.'),
})

export type SignalViewApi = zod.input<typeof SignalViewApi>
export type SignalViewApiOutput = zod.output<typeof SignalViewApi>

export const ImpactNumberKeyEnumApi = zod
    .enum(['tickets', 'query-hours'])
    .describe('\* `tickets` - Support tickets\n\* `query-hours` - Database hours')

export type ImpactNumberKeyEnumApi = zod.input<typeof ImpactNumberKeyEnumApi>
export type ImpactNumberKeyEnumApiOutput = zod.output<typeof ImpactNumberKeyEnumApi>

export const ImpactWorkingApi = zod.object({
    expression: zod.string().describe("How the number is worked out, such as '120 ms × 30,000 calls'."),
    result: zod.string().describe("What the working comes to, such as '1.00 hours a day'."),
})

export type ImpactWorkingApi = zod.input<typeof ImpactWorkingApi>
export type ImpactWorkingApiOutput = zod.output<typeof ImpactWorkingApi>

export const ImpactNumberApi = zod.object({
    key: zod
        .enum(['tickets', 'query-hours'])
        .describe('\* `tickets` - Support tickets\n\* `query-hours` - Database hours')
        .describe(
            'Which number this is: distinct support tickets or database hours a day.\n\n\* `tickets` - Support tickets\n\* `query-hours` - Database hours'
        ),
    value: zod.string().describe("The number as shown, such as '2' or '1 hour'."),
    sentence: zod.string().describe('The sentence that follows the number.'),
    signal: zod
        .union([
            zod.object({
                signal_id: zod.string().describe("The signal's id."),
                source_product: zod.string().describe('The product that emitted the signal.'),
                source_type: zod.string().describe('The kind of signal within its product.'),
                source_id: zod.string().describe('The id of the source object, such as an issue or a ticket.'),
                content: zod.string().describe("The signal's text as emitted."),
                timestamp: zod.iso.datetime({ offset: true }).describe('When the signal happened.'),
                extra: zod
                    .record(zod.string(), zod.unknown())
                    .describe(
                        "The emitter's extra fields as it sent them, used to link to the source object. Values are any JSON."
                    ),
                headline: zod.string().describe('The signal as one short line.'),
                lead: zod.string().describe("The signal's first sentence."),
                meta: zod.string().describe('Identifiers such as a pull request or ticket number, joined by dots.'),
                cited: zod
                    .union([zod.enum(['code', 'slack']).describe('\* `code` - Code\n\* `slack` - Slack'), zod.null()])
                    .describe(
                        'What a scout finding cites: code or a Slack thread.\n\n\* `code` - Code\n\* `slack` - Slack'
                    ),
                recording: zod
                    .union([
                        zod.object({
                            session_id: zod.string().describe("The recording's session id."),
                            start_at: zod.iso
                                .datetime({ offset: true })
                                .nullable()
                                .describe('Where the player starts, a few seconds before the finding.'),
                            offset: zod.string().nullable().describe("The finding's time in the recording, as MM:SS."),
                            seek_seconds: zod
                                .number()
                                .nullable()
                                .describe(
                                    'Where the player starts, in seconds from the recording start. Null without an offset.'
                                ),
                        }),
                        zod.null(),
                    ])
                    .describe('The recording the signal plays, if any.'),
                link: zod
                    .union([
                        zod.object({
                            url: zod.string().describe('Where the link goes, outside PostHog.'),
                            text: zod.string().describe('The link text.'),
                        }),
                        zod.null(),
                    ])
                    .describe('Where a scout finding links outside PostHog, if anywhere.'),
                preview: zod
                    .union([
                        zod.object({
                            hint: zod
                                .string()
                                .describe("What expanding the signal shows, such as 'Show the stack trace'."),
                            code: zod
                                .array(
                                    zod.object({
                                        repo: zod.string().describe('The repository as owner\/name.'),
                                        path: zod.string().describe('The file path in the repository.'),
                                    })
                                )
                                .describe("Repository files to quote, the finding's own file first."),
                            block: zod
                                .array(
                                    zod.object({
                                        text: zod.string().describe('One line of the preview block.'),
                                        quiet: zod
                                            .boolean()
                                            .describe('Whether the line is secondary, such as a stack frame.'),
                                    })
                                )
                                .describe('A preformatted block, such as a stack trace or a query.'),
                            text: zod.string().describe("The finding's text beyond its first sentence."),
                            facts: zod.array(zod.string()).describe('Short facts about the source.'),
                            link: zod
                                .union([
                                    zod.object({
                                        url: zod.string().describe('Where the link goes, outside PostHog.'),
                                        text: zod.string().describe('The link text.'),
                                    }),
                                    zod.null(),
                                ])
                                .describe("A link that replaces the signal's own destination."),
                            link_label: zod
                                .string()
                                .nullable()
                                .describe("A label that replaces the label of the signal's own destination."),
                        }),
                        zod.null(),
                    ])
                    .describe('What expanding the signal shows, if anything.'),
            }),
            zod.null(),
        ])
        .describe('The signal the number comes from, if one does.'),
    values: zod.array(zod.string()).describe("The figures in the signal's headline to mark."),
    working: zod
        .union([
            zod.object({
                expression: zod.string().describe("How the number is worked out, such as '120 ms × 30,000 calls'."),
                result: zod.string().describe("What the working comes to, such as '1.00 hours a day'."),
            }),
            zod.null(),
        ])
        .describe('How the number is worked out, if it is.'),
})

export type ImpactNumberApi = zod.input<typeof ImpactNumberApi>
export type ImpactNumberApiOutput = zod.output<typeof ImpactNumberApi>

export const ReportPageApi = zod.object({
    lead: zod.string().describe("The summary's opening paragraph, as markdown."),
    proposal: zod
        .string()
        .describe('The proposed fix cut to whole sentences, as markdown. Empty when the report proposes none.'),
    impact_sentence: zod
        .string()
        .describe(
            'The impact section cut to whole sentences, as markdown, when it states a measurement. Empty otherwise.'
        ),
    named_pull_request: zod
        .union([
            zod.object({
                url: zod.string().describe('The pull request on GitHub.'),
                number: zod.number().describe('The pull request number.'),
            }),
            zod.null(),
        ])
        .describe('The pull request the proposal names, or else the summary, when it names exactly one.'),
    solution_names_pull_request: zod.boolean().describe('Whether the proposal names any pull request.'),
    evidence: zod
        .array(
            zod.object({
                signal_id: zod.string().describe("The signal's id."),
                source_product: zod.string().describe('The product that emitted the signal.'),
                source_type: zod.string().describe('The kind of signal within its product.'),
                source_id: zod.string().describe('The id of the source object, such as an issue or a ticket.'),
                content: zod.string().describe("The signal's text as emitted."),
                timestamp: zod.iso.datetime({ offset: true }).describe('When the signal happened.'),
                extra: zod
                    .record(zod.string(), zod.unknown())
                    .describe(
                        "The emitter's extra fields as it sent them, used to link to the source object. Values are any JSON."
                    ),
                headline: zod.string().describe('The signal as one short line.'),
                lead: zod.string().describe("The signal's first sentence."),
                meta: zod.string().describe('Identifiers such as a pull request or ticket number, joined by dots.'),
                cited: zod
                    .union([zod.enum(['code', 'slack']).describe('\* `code` - Code\n\* `slack` - Slack'), zod.null()])
                    .describe(
                        'What a scout finding cites: code or a Slack thread.\n\n\* `code` - Code\n\* `slack` - Slack'
                    ),
                recording: zod
                    .union([
                        zod.object({
                            session_id: zod.string().describe("The recording's session id."),
                            start_at: zod.iso
                                .datetime({ offset: true })
                                .nullable()
                                .describe('Where the player starts, a few seconds before the finding.'),
                            offset: zod.string().nullable().describe("The finding's time in the recording, as MM:SS."),
                            seek_seconds: zod
                                .number()
                                .nullable()
                                .describe(
                                    'Where the player starts, in seconds from the recording start. Null without an offset.'
                                ),
                        }),
                        zod.null(),
                    ])
                    .describe('The recording the signal plays, if any.'),
                link: zod
                    .union([
                        zod.object({
                            url: zod.string().describe('Where the link goes, outside PostHog.'),
                            text: zod.string().describe('The link text.'),
                        }),
                        zod.null(),
                    ])
                    .describe('Where a scout finding links outside PostHog, if anywhere.'),
                preview: zod
                    .union([
                        zod.object({
                            hint: zod
                                .string()
                                .describe("What expanding the signal shows, such as 'Show the stack trace'."),
                            code: zod
                                .array(
                                    zod.object({
                                        repo: zod.string().describe('The repository as owner\/name.'),
                                        path: zod.string().describe('The file path in the repository.'),
                                    })
                                )
                                .describe("Repository files to quote, the finding's own file first."),
                            block: zod
                                .array(
                                    zod.object({
                                        text: zod.string().describe('One line of the preview block.'),
                                        quiet: zod
                                            .boolean()
                                            .describe('Whether the line is secondary, such as a stack frame.'),
                                    })
                                )
                                .describe('A preformatted block, such as a stack trace or a query.'),
                            text: zod.string().describe("The finding's text beyond its first sentence."),
                            facts: zod.array(zod.string()).describe('Short facts about the source.'),
                            link: zod
                                .union([
                                    zod.object({
                                        url: zod.string().describe('Where the link goes, outside PostHog.'),
                                        text: zod.string().describe('The link text.'),
                                    }),
                                    zod.null(),
                                ])
                                .describe("A link that replaces the signal's own destination."),
                            link_label: zod
                                .string()
                                .nullable()
                                .describe("A label that replaces the label of the signal's own destination."),
                        }),
                        zod.null(),
                    ])
                    .describe('What expanding the signal shows, if anything.'),
            })
        )
        .describe('The signals to show as evidence, at most 3, newest first, one per source first.'),
    source_count: zod
        .number()
        .describe(
            "How many distinct source objects the report's newest 100 signals come from. The impact numbers and last seen use the same signals."
        ),
    impact_numbers: zod
        .array(
            zod.object({
                key: zod
                    .enum(['tickets', 'query-hours'])
                    .describe('\* `tickets` - Support tickets\n\* `query-hours` - Database hours')
                    .describe(
                        'Which number this is: distinct support tickets or database hours a day.\n\n\* `tickets` - Support tickets\n\* `query-hours` - Database hours'
                    ),
                value: zod.string().describe("The number as shown, such as '2' or '1 hour'."),
                sentence: zod.string().describe('The sentence that follows the number.'),
                signal: zod
                    .union([
                        zod.object({
                            signal_id: zod.string().describe("The signal's id."),
                            source_product: zod.string().describe('The product that emitted the signal.'),
                            source_type: zod.string().describe('The kind of signal within its product.'),
                            source_id: zod
                                .string()
                                .describe('The id of the source object, such as an issue or a ticket.'),
                            content: zod.string().describe("The signal's text as emitted."),
                            timestamp: zod.iso.datetime({ offset: true }).describe('When the signal happened.'),
                            extra: zod
                                .record(zod.string(), zod.unknown())
                                .describe(
                                    "The emitter's extra fields as it sent them, used to link to the source object. Values are any JSON."
                                ),
                            headline: zod.string().describe('The signal as one short line.'),
                            lead: zod.string().describe("The signal's first sentence."),
                            meta: zod
                                .string()
                                .describe('Identifiers such as a pull request or ticket number, joined by dots.'),
                            cited: zod
                                .union([
                                    zod.enum(['code', 'slack']).describe('\* `code` - Code\n\* `slack` - Slack'),
                                    zod.null(),
                                ])
                                .describe(
                                    'What a scout finding cites: code or a Slack thread.\n\n\* `code` - Code\n\* `slack` - Slack'
                                ),
                            recording: zod
                                .union([
                                    zod.object({
                                        session_id: zod.string().describe("The recording's session id."),
                                        start_at: zod.iso
                                            .datetime({ offset: true })
                                            .nullable()
                                            .describe('Where the player starts, a few seconds before the finding.'),
                                        offset: zod
                                            .string()
                                            .nullable()
                                            .describe("The finding's time in the recording, as MM:SS."),
                                        seek_seconds: zod
                                            .number()
                                            .nullable()
                                            .describe(
                                                'Where the player starts, in seconds from the recording start. Null without an offset.'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .describe('The recording the signal plays, if any.'),
                            link: zod
                                .union([
                                    zod.object({
                                        url: zod.string().describe('Where the link goes, outside PostHog.'),
                                        text: zod.string().describe('The link text.'),
                                    }),
                                    zod.null(),
                                ])
                                .describe('Where a scout finding links outside PostHog, if anywhere.'),
                            preview: zod
                                .union([
                                    zod.object({
                                        hint: zod
                                            .string()
                                            .describe(
                                                "What expanding the signal shows, such as 'Show the stack trace'."
                                            ),
                                        code: zod
                                            .array(
                                                zod.object({
                                                    repo: zod.string().describe('The repository as owner\/name.'),
                                                    path: zod.string().describe('The file path in the repository.'),
                                                })
                                            )
                                            .describe("Repository files to quote, the finding's own file first."),
                                        block: zod
                                            .array(
                                                zod.object({
                                                    text: zod.string().describe('One line of the preview block.'),
                                                    quiet: zod
                                                        .boolean()
                                                        .describe(
                                                            'Whether the line is secondary, such as a stack frame.'
                                                        ),
                                                })
                                            )
                                            .describe('A preformatted block, such as a stack trace or a query.'),
                                        text: zod.string().describe("The finding's text beyond its first sentence."),
                                        facts: zod.array(zod.string()).describe('Short facts about the source.'),
                                        link: zod
                                            .union([
                                                zod.object({
                                                    url: zod.string().describe('Where the link goes, outside PostHog.'),
                                                    text: zod.string().describe('The link text.'),
                                                }),
                                                zod.null(),
                                            ])
                                            .describe("A link that replaces the signal's own destination."),
                                        link_label: zod
                                            .string()
                                            .nullable()
                                            .describe(
                                                "A label that replaces the label of the signal's own destination."
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .describe('What expanding the signal shows, if anything.'),
                        }),
                        zod.null(),
                    ])
                    .describe('The signal the number comes from, if one does.'),
                values: zod.array(zod.string()).describe("The figures in the signal's headline to mark."),
                working: zod
                    .union([
                        zod.object({
                            expression: zod
                                .string()
                                .describe("How the number is worked out, such as '120 ms × 30,000 calls'."),
                            result: zod.string().describe("What the working comes to, such as '1.00 hours a day'."),
                        }),
                        zod.null(),
                    ])
                    .describe('How the number is worked out, if it is.'),
            })
        )
        .describe('Numbers the signals size the problem with, such as distinct support tickets.'),
    last_seen: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the newest session, ticket or alert behind the report happened.'),
})

export type ReportPageApi = zod.input<typeof ReportPageApi>
export type ReportPageApiOutput = zod.output<typeof ReportPageApi>
