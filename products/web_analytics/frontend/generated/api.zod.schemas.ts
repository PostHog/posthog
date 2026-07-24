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

export const DirectionEnumApi = zod.enum(['Up', 'Down']).describe('\* `Up` - Up\n\* `Down` - Down')

export type DirectionEnumApi = zod.input<typeof DirectionEnumApi>
export type DirectionEnumApiOutput = zod.output<typeof DirectionEnumApi>

export const WoWChangeApi = zod.object({
    percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
    direction: zod
        .enum(['Up', 'Down'])
        .describe('\* `Up` - Up\n\* `Down` - Down')
        .describe('Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'),
    color: zod.string().describe('Hex color indicating whether the change is a positive or negative signal.'),
    text: zod.string().describe("Short label, e.g. 'Up 12%'."),
    long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
})

export type WoWChangeApi = zod.input<typeof WoWChangeApi>
export type WoWChangeApiOutput = zod.output<typeof WoWChangeApi>

export const NumericMetricApi = zod.object({
    current: zod.number().describe('Value for the most recent period.'),
    previous: zod.number().nullable().describe('Value for the prior period, if available.'),
    change: zod
        .union([
            zod.object({
                percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                direction: zod
                    .enum(['Up', 'Down'])
                    .describe('\* `Up` - Up\n\* `Down` - Down')
                    .describe(
                        'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                    ),
                color: zod
                    .string()
                    .describe('Hex color indicating whether the change is a positive or negative signal.'),
                text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
            }),
            zod.null(),
        ])
        .describe('Period-over-period change, null when not meaningful.'),
})

export type NumericMetricApi = zod.input<typeof NumericMetricApi>
export type NumericMetricApiOutput = zod.output<typeof NumericMetricApi>

export const DurationMetricApi = zod.object({
    current: zod.string().describe("Human-readable duration, e.g. '2m 34s'."),
    previous: zod.string().nullable().describe("Prior-period duration, e.g. '2m 10s'."),
    change: zod
        .union([
            zod.object({
                percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                direction: zod
                    .enum(['Up', 'Down'])
                    .describe('\* `Up` - Up\n\* `Down` - Down')
                    .describe(
                        'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                    ),
                color: zod
                    .string()
                    .describe('Hex color indicating whether the change is a positive or negative signal.'),
                text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
            }),
            zod.null(),
        ])
        .describe('Period-over-period change, null when not meaningful.'),
})

export type DurationMetricApi = zod.input<typeof DurationMetricApi>
export type DurationMetricApiOutput = zod.output<typeof DurationMetricApi>

export const TopPageApi = zod.object({
    host: zod.string().describe('Host for the page, if recorded.'),
    path: zod.string().describe('URL path.'),
    visitors: zod.number().describe('Unique visitors in the period.'),
    change: zod
        .union([
            zod.object({
                percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                direction: zod
                    .enum(['Up', 'Down'])
                    .describe('\* `Up` - Up\n\* `Down` - Down')
                    .describe(
                        'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                    ),
                color: zod
                    .string()
                    .describe('Hex color indicating whether the change is a positive or negative signal.'),
                text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
            }),
            zod.null(),
        ])
        .describe('Period-over-period change in visitors, null when not meaningful.'),
})

export type TopPageApi = zod.input<typeof TopPageApi>
export type TopPageApiOutput = zod.output<typeof TopPageApi>

export const TopSourceApi = zod.object({
    name: zod.string().describe('Initial referring domain.'),
    visitors: zod.number().describe('Unique visitors from this source.'),
    change: zod
        .union([
            zod.object({
                percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                direction: zod
                    .enum(['Up', 'Down'])
                    .describe('\* `Up` - Up\n\* `Down` - Down')
                    .describe(
                        'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                    ),
                color: zod
                    .string()
                    .describe('Hex color indicating whether the change is a positive or negative signal.'),
                text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
            }),
            zod.null(),
        ])
        .describe('Period-over-period change in visitors, null when not meaningful.'),
})

export type TopSourceApi = zod.input<typeof TopSourceApi>
export type TopSourceApiOutput = zod.output<typeof TopSourceApi>

export const GoalApi = zod.object({
    name: zod.string().describe('Goal name (action name).'),
    conversions: zod.number().describe('Total conversions in the period.'),
    change: zod
        .union([
            zod.object({
                percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                direction: zod
                    .enum(['Up', 'Down'])
                    .describe('\* `Up` - Up\n\* `Down` - Down')
                    .describe(
                        'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                    ),
                color: zod
                    .string()
                    .describe('Hex color indicating whether the change is a positive or negative signal.'),
                text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
            }),
            zod.null(),
        ])
        .describe('Period-over-period change in conversions, null when not meaningful.'),
})

export type GoalApi = zod.input<typeof GoalApi>
export type GoalApiOutput = zod.output<typeof GoalApi>

export const WeeklyDigestResponseApi = zod.object({
    visitors: zod
        .object({
            current: zod.number().describe('Value for the most recent period.'),
            previous: zod.number().nullable().describe('Value for the prior period, if available.'),
            change: zod
                .union([
                    zod.object({
                        percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                        direction: zod
                            .enum(['Up', 'Down'])
                            .describe('\* `Up` - Up\n\* `Down` - Down')
                            .describe(
                                'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                            ),
                        color: zod
                            .string()
                            .describe('Hex color indicating whether the change is a positive or negative signal.'),
                        text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                        long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
                    }),
                    zod.null(),
                ])
                .describe('Period-over-period change, null when not meaningful.'),
        })
        .describe('Unique visitors.'),
    pageviews: zod
        .object({
            current: zod.number().describe('Value for the most recent period.'),
            previous: zod.number().nullable().describe('Value for the prior period, if available.'),
            change: zod
                .union([
                    zod.object({
                        percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                        direction: zod
                            .enum(['Up', 'Down'])
                            .describe('\* `Up` - Up\n\* `Down` - Down')
                            .describe(
                                'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                            ),
                        color: zod
                            .string()
                            .describe('Hex color indicating whether the change is a positive or negative signal.'),
                        text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                        long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
                    }),
                    zod.null(),
                ])
                .describe('Period-over-period change, null when not meaningful.'),
        })
        .describe('Total pageviews.'),
    sessions: zod
        .object({
            current: zod.number().describe('Value for the most recent period.'),
            previous: zod.number().nullable().describe('Value for the prior period, if available.'),
            change: zod
                .union([
                    zod.object({
                        percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                        direction: zod
                            .enum(['Up', 'Down'])
                            .describe('\* `Up` - Up\n\* `Down` - Down')
                            .describe(
                                'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                            ),
                        color: zod
                            .string()
                            .describe('Hex color indicating whether the change is a positive or negative signal.'),
                        text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                        long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
                    }),
                    zod.null(),
                ])
                .describe('Period-over-period change, null when not meaningful.'),
        })
        .describe('Total sessions.'),
    bounce_rate: zod
        .object({
            current: zod.number().describe('Value for the most recent period.'),
            previous: zod.number().nullable().describe('Value for the prior period, if available.'),
            change: zod
                .union([
                    zod.object({
                        percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                        direction: zod
                            .enum(['Up', 'Down'])
                            .describe('\* `Up` - Up\n\* `Down` - Down')
                            .describe(
                                'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                            ),
                        color: zod
                            .string()
                            .describe('Hex color indicating whether the change is a positive or negative signal.'),
                        text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                        long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
                    }),
                    zod.null(),
                ])
                .describe('Period-over-period change, null when not meaningful.'),
        })
        .describe('Bounce rate (0–100).'),
    avg_session_duration: zod
        .object({
            current: zod.string().describe("Human-readable duration, e.g. '2m 34s'."),
            previous: zod.string().nullable().describe("Prior-period duration, e.g. '2m 10s'."),
            change: zod
                .union([
                    zod.object({
                        percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                        direction: zod
                            .enum(['Up', 'Down'])
                            .describe('\* `Up` - Up\n\* `Down` - Down')
                            .describe(
                                'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                            ),
                        color: zod
                            .string()
                            .describe('Hex color indicating whether the change is a positive or negative signal.'),
                        text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                        long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
                    }),
                    zod.null(),
                ])
                .describe('Period-over-period change, null when not meaningful.'),
        })
        .describe('Average session duration.'),
    top_pages: zod
        .array(
            zod.object({
                host: zod.string().describe('Host for the page, if recorded.'),
                path: zod.string().describe('URL path.'),
                visitors: zod.number().describe('Unique visitors in the period.'),
                change: zod
                    .union([
                        zod.object({
                            percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                            direction: zod
                                .enum(['Up', 'Down'])
                                .describe('\* `Up` - Up\n\* `Down` - Down')
                                .describe(
                                    'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                                ),
                            color: zod
                                .string()
                                .describe('Hex color indicating whether the change is a positive or negative signal.'),
                            text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                            long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
                        }),
                        zod.null(),
                    ])
                    .describe('Period-over-period change in visitors, null when not meaningful.'),
            })
        )
        .describe('Top 5 pages by unique visitors.'),
    top_sources: zod
        .array(
            zod.object({
                name: zod.string().describe('Initial referring domain.'),
                visitors: zod.number().describe('Unique visitors from this source.'),
                change: zod
                    .union([
                        zod.object({
                            percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                            direction: zod
                                .enum(['Up', 'Down'])
                                .describe('\* `Up` - Up\n\* `Down` - Down')
                                .describe(
                                    'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                                ),
                            color: zod
                                .string()
                                .describe('Hex color indicating whether the change is a positive or negative signal.'),
                            text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                            long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
                        }),
                        zod.null(),
                    ])
                    .describe('Period-over-period change in visitors, null when not meaningful.'),
            })
        )
        .describe('Top 5 traffic sources by unique visitors.'),
    goals: zod
        .array(
            zod.object({
                name: zod.string().describe('Goal name (action name).'),
                conversions: zod.number().describe('Total conversions in the period.'),
                change: zod
                    .union([
                        zod.object({
                            percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
                            direction: zod
                                .enum(['Up', 'Down'])
                                .describe('\* `Up` - Up\n\* `Down` - Down')
                                .describe(
                                    'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
                                ),
                            color: zod
                                .string()
                                .describe('Hex color indicating whether the change is a positive or negative signal.'),
                            text: zod.string().describe("Short label, e.g. 'Up 12%'."),
                            long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
                        }),
                        zod.null(),
                    ])
                    .describe('Period-over-period change in conversions, null when not meaningful.'),
            })
        )
        .describe('Goal conversions.'),
    dashboard_url: zod.url().describe('Link to the Web analytics dashboard for this project.'),
})

export type WeeklyDigestResponseApi = zod.input<typeof WeeklyDigestResponseApi>
export type WeeklyDigestResponseApiOutput = zod.output<typeof WeeklyDigestResponseApi>
