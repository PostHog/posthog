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
