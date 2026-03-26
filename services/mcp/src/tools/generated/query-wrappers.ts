// AUTO-GENERATED from services/mcp/definitions/query-wrappers.yaml + schema.json — do not edit
import { z } from 'zod'

import { createQueryWrapper } from '@/tools/query-wrapper-factory'
import type { ZodObjectAny } from '@/tools/types'

// --- Shared Zod schemas generated from schema.json ---

const integer = z.coerce.number().int()

const AssistantGroupMultipleBreakdownFilter = z.object({
    group_type_index: z
        .union([integer, z.null()])
        .describe('Index of the group type from the group mapping.')
        .optional(),
    property: z.string().describe('Property name from the plan to break down by.'),
    type: z.literal('group').default('group'),
})

const AssistantEventMultipleBreakdownFilterType = z.enum([
    'cohort',
    'person',
    'event',
    'event_metadata',
    'session',
    'hogql',
    'data_warehouse_person_property',
    'revenue_analytics',
])

const AssistantGenericMultipleBreakdownFilter = z.object({
    property: z.string().describe('Property name from the plan to break down by.'),
    type: AssistantEventMultipleBreakdownFilterType,
})

const AssistantMultipleBreakdownFilter = z.union([
    AssistantGroupMultipleBreakdownFilter,
    AssistantGenericMultipleBreakdownFilter,
])

const AssistantTrendsBreakdownFilter = z.object({
    breakdown_limit: integer.describe('How many distinct values to show.').default(25).optional(),
    breakdowns: z.array(AssistantMultipleBreakdownFilter).describe('Use this field to define breakdowns.'),
})

const CompareFilter = z.object({
    compare: z.coerce
        .boolean()
        .describe('Whether to compare the current date range to a previous date range.')
        .default(false)
        .optional(),
    compare_to: z
        .string()
        .describe(
            'The date range to compare to. The value is a relative date. Examples of relative dates are: `-1y` for 1 year ago, `-14m` for 14 months ago, `-100w` for 100 weeks ago, `-14d` for 14 days ago, `-30h` for 30 hours ago.'
        )
        .optional(),
})

const AssistantDateRange = z.object({
    date_from: z.string().describe('ISO8601 date string.'),
    date_to: z.string().nullable().describe('ISO8601 date string.').optional(),
})

const AssistantDurationRange = z.object({
    date_from: z
        .string()
        .describe(
            "Duration in the past. Supported units are: `h` (hour), `d` (day), `w` (week), `m` (month), `y` (year), `all` (all time). Use the `Start` suffix to define the exact left date boundary. Examples: `-1d` last day from now, `-180d` last 180 days from now, `mStart` this month start, `-1dStart` yesterday's start."
        ),
})

const AssistantDateRangeFilter = z.union([AssistantDateRange, AssistantDurationRange])

const IntervalType = z.enum(['second', 'minute', 'hour', 'day', 'week', 'month'])

const AssistantStringOrBooleanValuePropertyFilterOperator = z.enum([
    'exact',
    'is_not',
    'icontains',
    'not_icontains',
    'regex',
    'not_regex',
])

const AssistantGenericPropertyFilterType = z.enum(['event', 'person', 'session', 'feature'])

const AssistantNumericValuePropertyFilterOperator = z.enum(['exact', 'gt', 'lt'])

const AssistantArrayPropertyFilterOperator = z.enum(['exact', 'is_not'])

const AssistantDateTimePropertyFilterOperator = z.enum(['is_date_exact', 'is_date_before', 'is_date_after'])

const AssistantSetPropertyFilterOperator = z.enum(['is_set', 'is_not_set'])

const AssistantGenericPropertyFilter = z.union([
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantStringOrBooleanValuePropertyFilterOperator.describe(
            '`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` - matches the regex pattern. `not_regex` - does not match the regex pattern.'
        ),
        type: AssistantGenericPropertyFilterType,
        value: z
            .string()
            .describe(
                'Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be matched against the property value. Use the string values `true` or `false` for boolean properties.'
            ),
    }),
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantNumericValuePropertyFilterOperator,
        type: AssistantGenericPropertyFilterType,
        value: z.coerce.number(),
    }),
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantArrayPropertyFilterOperator.describe(
            '`exact` - exact match of any of the values. `is_not` - does not match any of the values.'
        ),
        type: AssistantGenericPropertyFilterType,
        value: z
            .array(z.string())
            .describe(
                'Only use property values from the plan. Always use strings as values. If you have a number, convert it to a string first. If you have a boolean, convert it to a string "true" or "false".'
            ),
    }),
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantDateTimePropertyFilterOperator,
        type: AssistantGenericPropertyFilterType,
        value: z.string().describe('Value must be a date in ISO 8601 format.'),
    }),
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantSetPropertyFilterOperator.describe(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't collected."
        ),
        type: AssistantGenericPropertyFilterType,
    }),
])

const AssistantGroupPropertyFilter = z.union([
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantStringOrBooleanValuePropertyFilterOperator.describe(
            '`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` - matches the regex pattern. `not_regex` - does not match the regex pattern.'
        ),
        type: z.literal('group').default('group'),
        value: z
            .string()
            .describe(
                'Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be matched against the property value. Use the string values `true` or `false` for boolean properties.'
            ),
    }),
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantNumericValuePropertyFilterOperator,
        type: z.literal('group').default('group'),
        value: z.coerce.number(),
    }),
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantArrayPropertyFilterOperator.describe(
            '`exact` - exact match of any of the values. `is_not` - does not match any of the values.'
        ),
        type: z.literal('group').default('group'),
        value: z
            .array(z.string())
            .describe(
                'Only use property values from the plan. Always use strings as values. If you have a number, convert it to a string first. If you have a boolean, convert it to a string "true" or "false".'
            ),
    }),
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantDateTimePropertyFilterOperator,
        type: z.literal('group').default('group'),
        value: z.string().describe('Value must be a date in ISO 8601 format.'),
    }),
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantSetPropertyFilterOperator.describe(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't collected."
        ),
        type: z.literal('group').default('group'),
    }),
])

const AssistantCohortPropertyFilter = z.object({
    key: z.literal('id').default('id'),
    operator: z.literal('in').default('in'),
    type: z
        .literal('cohort')
        .describe(
            'Filter events by cohort membership. Use this to narrow down results to persons belonging to a specific cohort. Example: `{ type: "cohort", key: "id", value: 42, operator: "in" }`'
        )
        .default('cohort'),
    value: integer.describe('The cohort ID to filter by.'),
})

const AssistantElementPropertyFilter = z.union([
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantStringOrBooleanValuePropertyFilterOperator.describe(
            '`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` - matches the regex pattern. `not_regex` - does not match the regex pattern.'
        ),
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
        value: z
            .string()
            .describe(
                'Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be matched against the property value. Use the string values `true` or `false` for boolean properties.'
            ),
    }),
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantNumericValuePropertyFilterOperator,
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
        value: z.coerce.number(),
    }),
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantArrayPropertyFilterOperator.describe(
            '`exact` - exact match of any of the values. `is_not` - does not match any of the values.'
        ),
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
        value: z
            .array(z.string())
            .describe(
                'Only use property values from the plan. Always use strings as values. If you have a number, convert it to a string first. If you have a boolean, convert it to a string "true" or "false".'
            ),
    }),
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantDateTimePropertyFilterOperator,
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
        value: z.string().describe('Value must be a date in ISO 8601 format.'),
    }),
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantSetPropertyFilterOperator.describe(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't collected."
        ),
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
    }),
])

const AssistantHogQLPropertyFilter = z.object({
    key: z
        .string()
        .describe(
            "A HogQL boolean expression used as a filter condition.\n\nExamples:\n- Filter where a property exceeds a threshold: `toFloat(properties.load_time) > 5.0`\n- Filter with string matching: `properties.$current_url LIKE '%/pricing%'`\n- Filter with multiple conditions: `properties.$browser = 'Chrome' AND toFloat(properties.duration) > 30`"
        ),
    type: z
        .literal('hogql')
        .describe(
            "Filter by a HogQL boolean expression for advanced filtering that can't be expressed with standard property filters."
        )
        .default('hogql'),
})

const AssistantFlagPropertyFilter = z.object({
    key: z.string().describe('The feature flag key.'),
    operator: z.literal('flag_evaluates_to').default('flag_evaluates_to'),
    type: z
        .literal('flag')
        .describe(
            'Filter events by feature flag state — only include events where a specific flag evaluated to a given value. Examples:\n- Flag enabled: `{ type: "flag", key: "new-onboarding", operator: "flag_evaluates_to", value: true }`\n- Specific variant: `{ type: "flag", key: "checkout-experiment", operator: "flag_evaluates_to", value: "variant-a" }`'
        )
        .default('flag'),
    value: z
        .union([z.coerce.boolean(), z.string()])
        .describe('`true`/`false` for boolean flags, or a variant name string for multivariate flags.'),
})

const AssistantPropertyFilter = z.union([
    AssistantGenericPropertyFilter,
    AssistantGroupPropertyFilter,
    AssistantCohortPropertyFilter,
    AssistantElementPropertyFilter,
    AssistantHogQLPropertyFilter,
    AssistantFlagPropertyFilter,
])

const BaseMathType = z.enum([
    'total',
    'dau',
    'weekly_active',
    'monthly_active',
    'unique_session',
    'first_time_for_user',
    'first_matching_event_for_user',
])

const FunnelMathType = z.enum(['total', 'first_time_for_user', 'first_time_for_user_with_filters'])

const PropertyMathType = z.enum(['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99'])

const CountPerActorMathType = z.enum([
    'avg_count_per_actor',
    'min_count_per_actor',
    'max_count_per_actor',
    'median_count_per_actor',
    'p75_count_per_actor',
    'p90_count_per_actor',
    'p95_count_per_actor',
    'p99_count_per_actor',
])

const GroupMathType = z.literal('unique_group')

const HogQLMathType = z.literal('hogql')

const ExperimentMetricMathType = z.enum([
    'total',
    'sum',
    'unique_session',
    'min',
    'max',
    'avg',
    'dau',
    'unique_group',
    'hogql',
])

const CalendarHeatmapMathType = z.enum(['total', 'dau'])

const MathType = z.union([
    BaseMathType,
    FunnelMathType,
    PropertyMathType,
    CountPerActorMathType,
    GroupMathType,
    HogQLMathType,
    ExperimentMetricMathType,
    CalendarHeatmapMathType,
])

const AssistantTrendsEventsNode = z.object({
    custom_name: z.string().optional(),
    event: z.string().nullable().describe('The event or `null` for all events.').optional(),
    kind: z.literal('EventsNode').default('EventsNode'),
    math: MathType.optional(),
    math_group_type_index: z.union([z.literal(0), z.literal(1), z.literal(2), z.literal(3), z.literal(4)]).optional(),
    math_hogql: z
        .string()
        .describe(
            'Custom HogQL expression for aggregation. Use when the predefined `math` types are not sufficient. When set, `math` must be set to `hogql`.\n\nExamples:\n- Sum a numeric property: `sum(toFloat(properties.$revenue))`\n- Average of a property: `avg(toFloat(properties.load_time))`\n- Count distinct values: `count(distinct properties.$session_id)`\n- Conditional count: `countIf(toFloat(properties.duration) > 30)`\n- Percentile: `quantile(0.95)(toFloat(properties.response_time))`'
        )
        .optional(),
    math_multiplier: z.coerce.number().optional(),
    math_property: z.string().optional(),
    math_property_type: z.string().optional(),
    name: z.string().optional(),
    optionalInFunnel: z.coerce.boolean().optional(),
    properties: z.array(AssistantPropertyFilter).optional(),
    version: z.coerce.number().describe('version of the node, used for schema migrations').optional(),
})

const AssistantTrendsActionsNode = z.object({
    custom_name: z.string().optional(),
    id: integer,
    kind: z.literal('ActionsNode').default('ActionsNode'),
    math: MathType.optional(),
    math_group_type_index: z.union([z.literal(0), z.literal(1), z.literal(2), z.literal(3), z.literal(4)]).optional(),
    math_hogql: z
        .string()
        .describe(
            'Custom HogQL expression for aggregation. Use when the predefined `math` types are not sufficient. When set, `math` must be set to `hogql`.\n\nExamples:\n- Sum a numeric property: `sum(toFloat(properties.$revenue))`\n- Average of a property: `avg(toFloat(properties.load_time))`\n- Count distinct values: `count(distinct properties.$session_id)`\n- Conditional count: `countIf(toFloat(properties.duration) > 30)`\n- Percentile: `quantile(0.95)(toFloat(properties.response_time))`'
        )
        .optional(),
    math_multiplier: z.coerce.number().optional(),
    math_property: z.string().optional(),
    math_property_type: z.string().optional(),
    name: z.string().describe('Action name from the plan.'),
    optionalInFunnel: z.coerce.boolean().optional(),
    properties: z.array(AssistantPropertyFilter).optional(),
    version: z.coerce.number().describe('version of the node, used for schema migrations').optional(),
})

const AggregationAxisFormat = z.enum([
    'numeric',
    'duration',
    'duration_ms',
    'percentage',
    'percentage_scaled',
    'currency',
    'short',
])

const TrendsFormulaNode = z.object({
    custom_name: z.string().describe('Optional user-defined name for the formula').optional(),
    formula: z.string(),
})

const AssistantTrendsFilter = z.object({
    aggregationAxisFormat: AggregationAxisFormat.describe(
        'Formats the trends value axis. Do not use the formatting unless you are absolutely sure that formatting will match the data. `numeric` - no formatting. Prefer this option by default. `duration` - formats the value in seconds to a human-readable duration, e.g., `132` becomes `2 minutes 12 seconds`. Use this option only if you are sure that the values are in seconds. `duration_ms` - formats the value in miliseconds to a human-readable duration, e.g., `1050` becomes `1 second 50 milliseconds`. Use this option only if you are sure that the values are in miliseconds. `percentage` - adds a percentage sign to the value, e.g., `50` becomes `50%`. `percentage_scaled` - formats the value as a percentage scaled to 0-100, e.g., `0.5` becomes `50%`. `currency` - formats the value as a currency, e.g., `1000` becomes `$1,000`.'
    )
        .default('numeric')
        .optional(),
    aggregationAxisPostfix: z
        .string()
        .describe(
            'Custom postfix to add to the aggregation axis, e.g., ` clicks` to format 5 as `5 clicks`. You may need to add a space before postfix.'
        )
        .optional(),
    aggregationAxisPrefix: z
        .string()
        .describe(
            'Custom prefix to add to the aggregation axis, e.g., `$` for USD dollars. You may need to add a space after prefix.'
        )
        .optional(),
    decimalPlaces: z.coerce
        .number()
        .describe(
            'Number of decimal places to show. Do not add this unless you are sure that values will have a decimal point.'
        )
        .optional(),
    display: z
        .enum([
            'Auto',
            'ActionsLineGraph',
            'ActionsBar',
            'ActionsUnstackedBar',
            'ActionsAreaGraph',
            'ActionsLineGraphCumulative',
            'BoldNumber',
            'ActionsPie',
            'ActionsBarValue',
            'ActionsTable',
            'WorldMap',
            'CalendarHeatmap',
            'TwoDimensionalHeatmap',
            'BoxPlot',
        ])
        .describe(
            'Visualization type. Available values: `ActionsLineGraph` - time-series line chart; most common option, as it shows change over time. `ActionsBar` - time-series bar chart. `ActionsAreaGraph` - time-series area chart. `ActionsLineGraphCumulative` - cumulative time-series line chart; good for cumulative metrics. `BoldNumber` - total value single large number. Use when user explicitly asks for a single output number. You CANNOT use this with breakdown or if the insight has more than one series. `ActionsBarValue` - total value (NOT time-series) bar chart; good for categorical data. `ActionsPie` - total value pie chart; good for visualizing proportions. `ActionsTable` - total value table; good when using breakdown to list users or other entities. `WorldMap` - total value world map; use when breaking down by country name using property `$geoip_country_name`, and only then.'
        )
        .default('ActionsLineGraph')
        .optional(),
    formulaNodes: z
        .array(TrendsFormulaNode)
        .describe(
            'Use custom formulas to perform mathematical operations like calculating percentages or metrics. Use the following syntax: `A/B`, where `A` and `B` are the names of the series. You can combine math aggregations and formulas. When using a formula, you must:\n- Identify and specify **all** events and actions needed to solve the formula.\n- Carefully review the list of available events and actions to find appropriate entities for each part of the formula.\n- Ensure that you find events and actions corresponding to both the numerator and denominator in ratio calculations. Examples of using math formulas:\n- If you want to calculate the percentage of users who have completed onboarding, you need to find and use events or actions similar to `$identify` and `onboarding complete`, so the formula will be `A / B`, where `A` is `onboarding complete` (unique users) and `B` is `$identify` (unique users).'
        )
        .optional(),
    showAlertThresholdLines: z.coerce
        .boolean()
        .describe('Whether to show alert threshold lines on the chart.')
        .default(false)
        .optional(),
    showLabelsOnSeries: z.coerce.boolean().describe('Whether to show labels on each series.').default(false).optional(),
    showLegend: z.coerce
        .boolean()
        .describe('Whether to show the legend describing series and breakdowns.')
        .default(false)
        .optional(),
    showMultipleYAxes: z.coerce
        .boolean()
        .describe('Whether to show multiple y-axes for different series.')
        .default(false)
        .optional(),
    showPercentStackView: z.coerce
        .boolean()
        .describe('Whether to show a percentage of each series. Use only with')
        .default(false)
        .optional(),
    showValuesOnSeries: z.coerce
        .boolean()
        .describe('Whether to show a value on each data point.')
        .default(false)
        .optional(),
    smoothingIntervals: integer.describe('Smoothing intervals for the trend line.').default(1).optional(),
    yAxisScaleType: z.enum(['log10', 'linear']).describe('Whether to scale the y-axis.').default('linear').optional(),
})

const AssistantTrendsQuery = z.object({
    aggregation_group_type_index: z.union([integer, z.null()]).describe('Groups aggregation').optional(),
    breakdownFilter: AssistantTrendsBreakdownFilter.describe(
        'Breakdowns are used to segment data by property values of maximum three properties. They divide all defined trends series to multiple subseries based on the values of the property. Include breakdowns **only when they are essential to directly answer the user’s question**. You must not add breakdowns if the question can be addressed without additional segmentation. Always use the minimum set of breakdowns needed to answer the question. When using breakdowns, you must:\n- **Identify the property group** and name for each breakdown.\n- **Provide the property name** for each breakdown.\n- **Validate that the property value accurately reflects the intended criteria**. Examples of using breakdowns:\n- page views trend by country: you need to find a property such as `$geoip_country_code` and set it as a breakdown.\n- number of users who have completed onboarding by an organization: you need to find a property such as `organization name` and set it as a breakdown.'
    ).optional(),
    compareFilter: CompareFilter.describe('Compare to date range').optional(),
    dateRange: AssistantDateRangeFilter.describe('Date range for the query').optional(),
    filterTestAccounts: z.coerce
        .boolean()
        .describe('Exclude internal and test users by applying the respective filters')
        .default(false)
        .optional(),
    interval: IntervalType.describe('Granularity of the response. Can be one of `hour`, `day`, `week` or `month`')
        .default('day')
        .optional(),
    kind: z.literal('TrendsQuery').default('TrendsQuery'),
    properties: z.array(AssistantPropertyFilter).describe('Property filters for all series').default([]).optional(),
    series: z
        .array(z.union([AssistantTrendsEventsNode, AssistantTrendsActionsNode]))
        .describe('Events or actions to include. Prioritize the more popular and fresh events and actions.'),
    trendsFilter: AssistantTrendsFilter.describe('Properties specific to the trends insight').optional(),
})

const AssistantFunnelsBreakdownType = z.enum(['person', 'event', 'group', 'session'])

const AssistantFunnelsBreakdownFilter = z.object({
    breakdown: z.string().describe('The entity property to break down by.'),
    breakdown_group_type_index: z
        .union([integer, z.null()])
        .describe(
            'If `breakdown_type` is `group`, this is the index of the group. Use the index from the group mapping.'
        )
        .optional(),
    breakdown_limit: integer.describe('How many distinct values to show.').default(25).optional(),
    breakdown_type: AssistantFunnelsBreakdownType.describe(
        'Type of the entity to break down by. If `group` is used, you must also provide `breakdown_group_type_index` from the group mapping.'
    ).default('event'),
})

const BreakdownAttributionType = z.enum(['first_touch', 'last_touch', 'all_events', 'step'])

const AssistantFunnelsExclusionEventsNode = z.object({
    event: z.string(),
    funnelFromStep: integer,
    funnelToStep: integer,
    kind: z.literal('EventsNode').default('EventsNode'),
})

const StepOrderValue = z.enum(['strict', 'unordered', 'ordered'])

const FunnelStepReference = z.enum(['total', 'previous'])

const FunnelVizType = z.enum(['steps', 'time_to_convert', 'trends', 'flow'])

const FunnelConversionWindowTimeUnit = z.enum(['second', 'minute', 'hour', 'day', 'week', 'month'])

const FunnelLayout = z.enum(['horizontal', 'vertical'])

const AssistantFunnelsFilter = z.object({
    binCount: z.coerce
        .number()
        .int()
        .describe(
            'Use this setting only when `funnelVizType` is `time_to_convert`: number of bins to show in histogram.'
        )
        .optional(),
    breakdownAttributionType: BreakdownAttributionType.describe(
        'Controls how the breakdown value is attributed to a specific step. `first_touch` - the breakdown value is the first property value found in the entire funnel. `last_touch` - the breakdown value is the last property value found in the entire funnel. `all_events` - the breakdown value must be present in all steps of the funnel. `step` - the breakdown value is the property value found at a specific step defined by `breakdownAttributionValue`.'
    )
        .default('first_touch')
        .optional(),
    breakdownAttributionValue: z.coerce
        .number()
        .int()
        .describe(
            'When `breakdownAttributionType` is `step`, this is the step number (0-indexed) to attribute the breakdown value to.'
        )
        .optional(),
    exclusions: z
        .array(AssistantFunnelsExclusionEventsNode)
        .describe(
            "Users may want to use exclusion events to filter out conversions in which a particular event occurred between specific steps. These events must not be included in the main sequence. This doesn't exclude users who have completed the event before or after the funnel sequence, but often this is what users want. (If not sure, worth clarifying.) You must include start and end indexes for each exclusion where the minimum index is one and the maximum index is the number of steps in the funnel. For example, there is a sequence with three steps: sign up, finish onboarding, purchase. If the user wants to exclude all conversions in which users left the page before finishing the onboarding, the exclusion step would be the event `$pageleave` with start index 2 and end index 3. When exclusion steps appear needed when you're planning the query, make sure to explicitly state this in the plan."
        )
        .default([])
        .optional(),
    funnelAggregateByHogQL: z
        .union([z.literal('properties.$session_id'), z.literal(null)])
        .describe('Use this field only if the user explicitly asks to aggregate the funnel by unique sessions.')
        .default(null)
        .optional(),
    funnelOrderType: StepOrderValue.describe(
        "Defines the behavior of event matching between steps. Prefer the `strict` option unless explicitly told to use a different one. `ordered` - defines a sequential funnel. Step B must happen after Step A, but any number of events can happen between A and B. `strict` - defines a funnel where all events must happen in order. Step B must happen directly after Step A without any events in between. `any` - order doesn't matter. Steps can be completed in any sequence."
    )
        .default('ordered')
        .optional(),
    funnelStepReference: FunnelStepReference.describe(
        'Whether conversion shown in the graph should be across all steps or just relative to the previous step.'
    )
        .default('total')
        .optional(),
    funnelVizType: FunnelVizType.describe(
        'Defines the type of visualization to use. The `steps` option is recommended. `steps` - shows a step-by-step funnel. Perfect to show a conversion rate of a sequence of events (default). `time_to_convert` - shows a histogram of the time it took to complete the funnel. `trends` - shows trends of the conversion rate of the whole sequence over time.'
    )
        .default('steps')
        .optional(),
    funnelWindowInterval: integer
        .describe(
            "Controls a time frame value for a conversion to be considered. Select a reasonable value based on the user's query. If needed, this can be practically unlimited by setting a large value, though it's rare to need that. Use in combination with `funnelWindowIntervalUnit`. The default value is 14 days."
        )
        .default(14)
        .optional(),
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.describe(
        "Controls a time frame interval for a conversion to be considered. Select a reasonable value based on the user's query. Use in combination with `funnelWindowInterval`. The default value is 14 days."
    )
        .default('day')
        .optional(),
    layout: FunnelLayout.describe('Controls how the funnel chart is displayed: vertically (preferred) or horizontally.')
        .default('vertical')
        .optional(),
})

const AssistantFunnelsMath = z.enum(['first_time_for_user', 'first_time_for_user_with_filters'])

const AssistantFunnelsEventsNode = z.object({
    custom_name: z.string().describe('Optional custom name for the event if it is needed to be renamed.').optional(),
    event: z.string().describe('Name of the event.'),
    kind: z.literal('EventsNode').default('EventsNode'),
    math: AssistantFunnelsMath.describe(
        'Optional math aggregation type for the series. Only specify this math type if the user wants one of these. `first_time_for_user` - counts the number of users who have completed the event for the first time ever. `first_time_for_user_with_filters` - counts the number of users who have completed the event with specified filters for the first time.'
    ).optional(),
    properties: z.array(AssistantPropertyFilter).optional(),
    version: z.coerce.number().describe('version of the node, used for schema migrations').optional(),
})

const AssistantFunnelsActionsNode = z.object({
    id: z.coerce.number().describe('Action ID from the plan.'),
    kind: z.literal('ActionsNode').default('ActionsNode'),
    math: AssistantFunnelsMath.describe(
        'Optional math aggregation type for the series. Only specify this math type if the user wants one of these. `first_time_for_user` - counts the number of users who have completed the event for the first time ever. `first_time_for_user_with_filters` - counts the number of users who have completed the event with specified filters for the first time.'
    ).optional(),
    name: z.string().describe('Action name from the plan.'),
    properties: z.array(AssistantPropertyFilter).optional(),
    version: z.coerce.number().describe('version of the node, used for schema migrations').optional(),
})

const AssistantFunnelsNode = z.union([AssistantFunnelsEventsNode, AssistantFunnelsActionsNode])

const AssistantFunnelsQuery = z.object({
    aggregation_group_type_index: integer
        .describe(
            'Use this field to define the aggregation by a specific group from the provided group mapping, which is NOT users or sessions.'
        )
        .optional(),
    breakdownFilter: AssistantFunnelsBreakdownFilter.describe(
        'A breakdown is used to segment data by a single property value. They divide all defined funnel series into multiple subseries based on the values of the property. Include a breakdown **only when it is essential to directly answer the user’s question**. You must not add a breakdown if the question can be addressed without additional segmentation. When using breakdowns, you must:\n- **Identify the property group** and name for a breakdown.\n- **Provide the property name** for a breakdown.\n- **Validate that the property value accurately reflects the intended criteria**. Examples of using a breakdown:\n- page views to sign up funnel by country: you need to find a property such as `$geoip_country_code` and set it as a breakdown.\n- conversion rate of users who have completed onboarding after signing up by an organization: you need to find a property such as `organization name` and set it as a breakdown.'
    ).optional(),
    dateRange: AssistantDateRangeFilter.describe('Date range for the query').optional(),
    filterTestAccounts: z.coerce
        .boolean()
        .describe('Exclude internal and test users by applying the respective filters')
        .default(false)
        .optional(),
    funnelsFilter: AssistantFunnelsFilter.describe('Properties specific to the funnels insight').optional(),
    interval: IntervalType.describe(
        'Granularity of the response. Can be one of `hour`, `day`, `week` or `month`'
    ).optional(),
    kind: z.literal('FunnelsQuery').default('FunnelsQuery'),
    properties: z.array(AssistantPropertyFilter).describe('Property filters for all series').default([]).optional(),
    series: z
        .array(AssistantFunnelsNode)
        .describe('Events or actions to include. Prioritize the more popular and fresh events and actions.'),
})

const RetentionPeriod = z.enum(['Hour', 'Day', 'Week', 'Month'])

const RetentionType = z.enum(['retention_recurring', 'retention_first_time', 'retention_first_ever_occurrence'])

const AssistantRetentionEventsNode = z.object({
    custom_name: z.string().describe('Custom name for the event if it is needed to be renamed.').optional(),
    name: z.string().describe('Event name from the plan.'),
    properties: z.array(AssistantPropertyFilter).describe('Property filters for the event.').optional(),
    type: z.literal('events').default('events'),
})

const AssistantRetentionActionsNode = z.object({
    id: z.coerce.number().describe('Action ID from the plan.'),
    name: z.string().describe('Action name from the plan.'),
    properties: z.array(AssistantPropertyFilter).describe('Property filters for the action.').optional(),
    type: z.literal('actions').default('actions'),
})

const AssistantRetentionEntity = z.union([AssistantRetentionEventsNode, AssistantRetentionActionsNode])

const AssistantRetentionFilter = z.object({
    aggregationProperty: z
        .string()
        .describe('The event or person property to aggregate when aggregationType is sum or avg.')
        .optional(),
    aggregationPropertyType: z
        .enum(['event', 'person'])
        .describe('The type of property to aggregate on (event or person). Defaults to event.')
        .default('event')
        .optional(),
    aggregationType: z
        .enum(['count', 'sum', 'avg'])
        .describe('The aggregation type to use for retention.')
        .default('count')
        .optional(),
    cumulative: z.coerce
        .boolean()
        .describe(
            'Whether retention should be rolling (aka unbounded, cumulative). Rolling retention means that a user coming back in period 5 makes them count towards all the previous periods.'
        )
        .optional(),
    meanRetentionCalculation: z
        .enum(['simple', 'weighted', 'none'])
        .describe(
            'Whether an additional series should be shown, showing the mean conversion for each period across cohorts.'
        )
        .optional(),
    minimumOccurrences: integer
        .describe('Minimum number of times an event must occur to count towards retention.')
        .optional(),
    period: RetentionPeriod.describe('Retention period, the interval to track cohorts by.').default('Day').optional(),
    retentionCustomBrackets: z
        .array(z.coerce.number())
        .describe('Custom brackets for retention calculations.')
        .optional(),
    retentionReference: z
        .enum(['total', 'previous'])
        .describe('Whether retention is with regard to initial cohort size, or that of the previous period.')
        .optional(),
    retentionType: RetentionType.describe(
        'Retention type: recurring or first time. Recurring retention counts a user as part of a cohort if they performed the cohort event during that time period, irrespective of it was their first time or not. First time retention only counts a user as part of the cohort if it was their first time performing the cohort event.'
    ).optional(),
    returningEntity: AssistantRetentionEntity.describe('Retention event (event marking the user coming back).'),
    targetEntity: AssistantRetentionEntity.describe(
        'Activation event (event putting the actor into the initial cohort).'
    ),
    timeWindowMode: z
        .enum(['strict_calendar_dates', '24_hour_windows'])
        .describe('The time window mode to use for retention calculations.')
        .optional(),
    totalIntervals: integer
        .describe(
            'How many intervals to show in the chart. The default value is 8 (meaning 7 periods after initial cohort).'
        )
        .default(8)
        .optional(),
})

const AssistantRetentionQuery = z.object({
    aggregation_group_type_index: z.union([integer, z.null()]).describe('Groups aggregation').optional(),
    dateRange: AssistantDateRangeFilter.describe('Date range for the query').optional(),
    filterTestAccounts: z.coerce
        .boolean()
        .describe('Exclude internal and test users by applying the respective filters')
        .default(false)
        .optional(),
    kind: z.literal('RetentionQuery').default('RetentionQuery'),
    properties: z.array(AssistantPropertyFilter).describe('Property filters for all series').default([]).optional(),
    retentionFilter: AssistantRetentionFilter.describe('Properties specific to the retention insight'),
})

const DateRange = z.object({
    date_from: z.string().nullable().optional(),
    date_to: z.string().nullable().optional(),
    explicitDate: z.coerce
        .boolean()
        .nullable()
        .describe(
            'Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period.'
        )
        .default(false)
        .optional(),
})

const PropertyOperator = z.enum([
    'exact',
    'is_not',
    'icontains',
    'not_icontains',
    'regex',
    'not_regex',
    'gt',
    'gte',
    'lt',
    'lte',
    'is_set',
    'is_not_set',
    'is_date_exact',
    'is_date_before',
    'is_date_after',
    'between',
    'not_between',
    'min',
    'max',
    'in',
    'not_in',
    'is_cleaned_path_exact',
    'flag_evaluates_to',
    'semver_eq',
    'semver_neq',
    'semver_gt',
    'semver_gte',
    'semver_lt',
    'semver_lte',
    'semver_tilde',
    'semver_caret',
    'semver_wildcard',
    'icontains_multi',
    'not_icontains_multi',
])

const PropertyFilterBaseValue = z.union([z.string(), z.coerce.number(), z.coerce.boolean()])

const PropertyFilterValue = z.union([PropertyFilterBaseValue, z.array(PropertyFilterBaseValue), z.null()])

const EventPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator.default('exact'),
    type: z.literal('event').describe('Event properties').default('event'),
    value: PropertyFilterValue.optional(),
})

const PersonPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('person').describe('Person properties').default('person'),
    value: PropertyFilterValue.optional(),
})

const ElementPropertyFilter = z.object({
    key: z.enum(['tag_name', 'text', 'href', 'selector']),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('element').default('element'),
    value: PropertyFilterValue.optional(),
})

const EventMetadataPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('event_metadata').default('event_metadata'),
    value: PropertyFilterValue.optional(),
})

const SessionPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('session').default('session'),
    value: PropertyFilterValue.optional(),
})

const CohortPropertyFilter = z.object({
    cohort_name: z.string().optional(),
    key: z.literal('id').default('id'),
    label: z.string().optional(),
    operator: PropertyOperator.default('in'),
    type: z.literal('cohort').default('cohort'),
    value: z.coerce.number().int(),
})

const DurationType = z.enum(['duration', 'active_seconds', 'inactive_seconds'])

const RecordingPropertyFilter = z.object({
    key: z.union([DurationType, z.literal('snapshot_source'), z.literal('visited_page'), z.literal('comment_text')]),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('recording').default('recording'),
    value: PropertyFilterValue.optional(),
})

const LogEntryPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('log_entry').default('log_entry'),
    value: PropertyFilterValue.optional(),
})

const GroupPropertyFilter = z.object({
    group_key_names: z.object({}).optional(),
    group_type_index: z.union([z.coerce.number().int(), z.null()]).optional(),
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('group').default('group'),
    value: PropertyFilterValue.optional(),
})

const FeaturePropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('feature').describe('Event property with "$feature/" prepended').default('feature'),
    value: PropertyFilterValue.optional(),
})

const FlagPropertyFilter = z.object({
    key: z.string().describe('The key should be the flag ID'),
    label: z.string().optional(),
    operator: z
        .literal('flag_evaluates_to')
        .describe('Only flag_evaluates_to operator is allowed for flag dependencies')
        .default('flag_evaluates_to'),
    type: z.literal('flag').describe('Feature flag dependency').default('flag'),
    value: z.union([z.coerce.boolean(), z.string()]).describe('The value can be true, false, or a variant name'),
})

const HogQLPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    type: z.literal('hogql').default('hogql'),
    value: PropertyFilterValue.optional(),
})

const EmptyPropertyFilter = z.object({
    type: z.literal('empty').default('empty').optional(),
})

const DataWarehousePropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('data_warehouse').default('data_warehouse'),
    value: PropertyFilterValue.optional(),
})

const DataWarehousePersonPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('data_warehouse_person_property').default('data_warehouse_person_property'),
    value: PropertyFilterValue.optional(),
})

const ErrorTrackingIssueFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('error_tracking_issue').default('error_tracking_issue'),
    value: PropertyFilterValue.optional(),
})

const LogPropertyFilterType = z.enum(['log', 'log_attribute', 'log_resource_attribute'])

const LogPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: LogPropertyFilterType,
    value: PropertyFilterValue.optional(),
})

const RevenueAnalyticsPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('revenue_analytics').default('revenue_analytics'),
    value: PropertyFilterValue.optional(),
})

const AnyPropertyFilter = z.union([
    EventPropertyFilter,
    PersonPropertyFilter,
    ElementPropertyFilter,
    EventMetadataPropertyFilter,
    SessionPropertyFilter,
    CohortPropertyFilter,
    RecordingPropertyFilter,
    LogEntryPropertyFilter,
    GroupPropertyFilter,
    FeaturePropertyFilter,
    FlagPropertyFilter,
    HogQLPropertyFilter,
    EmptyPropertyFilter,
    DataWarehousePropertyFilter,
    DataWarehousePersonPropertyFilter,
    ErrorTrackingIssueFilter,
    LogPropertyFilter,
    RevenueAnalyticsPropertyFilter,
])

const TracesQuery = z.object({
    dateRange: DateRange.optional(),
    filterSupportTraces: z.coerce.boolean().optional(),
    filterTestAccounts: z.coerce.boolean().optional(),
    groupKey: z.string().optional(),
    groupTypeIndex: integer.optional(),
    kind: z.literal('TracesQuery').default('TracesQuery'),
    limit: integer.optional(),
    offset: integer.optional(),
    personId: z.string().describe('Person who performed the event').optional(),
    properties: z.array(AnyPropertyFilter).describe('Properties configurable in the interface').optional(),
    randomOrder: z.coerce
        .boolean()
        .describe(
            'Use random ordering instead of timestamp DESC. Useful for representative sampling to avoid recency bias.'
        )
        .optional(),
})

// --- Tool registrations ---

export const GENERATED_TOOLS: Record<string, ReturnType<typeof createQueryWrapper<ZodObjectAny>>> = {
    'query-trends': createQueryWrapper({
        name: 'query-trends',
        schema: AssistantTrendsQuery,
        kind: 'TrendsQuery',
        uiResourceUri: 'ui://posthog/query-results.html',
    }),
    'query-funnel': createQueryWrapper({
        name: 'query-funnel',
        schema: AssistantFunnelsQuery,
        kind: 'FunnelsQuery',
        uiResourceUri: 'ui://posthog/query-results.html',
    }),
    'query-retention': createQueryWrapper({
        name: 'query-retention',
        schema: AssistantRetentionQuery,
        kind: 'RetentionQuery',
        uiResourceUri: 'ui://posthog/query-results.html',
    }),
    'query-traces-list': createQueryWrapper({ name: 'query-traces-list', schema: TracesQuery, kind: 'TracesQuery' }),
}
