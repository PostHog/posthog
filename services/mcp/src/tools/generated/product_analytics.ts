// AUTO-GENERATED from products/product_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    InsightsActivityRetrieveParams,
    InsightsActivityRetrieveQueryParams,
    InsightsAllActivityRetrieveQueryParams,
    InsightsCreateBody,
    InsightsDestroyParams,
    InsightsListQueryParams,
    InsightsPartialUpdateBody,
    InsightsPartialUpdateParams,
    InsightsRetrieveParams,
    InsightsRetrieveQueryParams,
    InsightsTrendingRetrieveQueryParams,
} from '@/generated/product_analytics/api'
import { castStringToInt } from '@/tools/cast-helpers'
import { withPostHogUrl, omitResponseFields, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

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
    'person',
    'event',
    'event_metadata',
    'session',
    'hogql',
    'cohort',
    'revenue_analytics',
    'data_warehouse',
    'data_warehouse_person_property',
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
    breakdown_path_cleaning: z.coerce
        .boolean()
        .describe(
            "When `true`, applies the project's configured path cleaning rules to URL or path breakdown values (e.g. `$pathname`, `$current_url`). Use this whenever the user asks for a breakdown by a URL or path property and there is no specific reason to keep the raw values. The user does not need to provide a regex — path cleaning rules come from the project's settings."
        )
        .optional(),
    breakdowns: z.array(AssistantMultipleBreakdownFilter).max(3).describe('Use this field to define breakdowns.'),
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
    operator: z.enum(['in', 'not_in']).default('in'),
    type: z
        .literal('cohort')
        .describe(
            'Filter events by cohort membership. Use this to narrow down results to persons belonging to a specific cohort. Use `operator: "in"` to include cohort members, or `operator: "not_in"` to exclude them. Examples:\n- Include: `{ type: "cohort", key: "id", value: 42, operator: "in" }`\n- Exclude: `{ type: "cohort", key: "id", value: 42, operator: "not_in" }`'
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

const AssistantTrendsGroupNode = z.object({
    custom_name: z.string().optional(),
    kind: z.literal('GroupNode').default('GroupNode'),
    math: MathType.describe(
        'Math aggregation for the combined series. The engine reads aggregation from here, not from inner nodes.'
    ).optional(),
    math_group_type_index: z.union([z.literal(0), z.literal(1), z.literal(2), z.literal(3), z.literal(4)]).optional(),
    math_hogql: z.string().describe('Custom HogQL aggregation. When set, `math` must be `hogql`.').optional(),
    math_multiplier: z.coerce.number().optional(),
    math_property: z.string().optional(),
    math_property_type: z.string().optional(),
    name: z.string().describe('Display name for the combined series.').optional(),
    nodes: z
        .array(z.union([AssistantTrendsEventsNode, AssistantTrendsActionsNode]))
        .min(2)
        .describe(
            "Events and actions combined into the series. Mirror the group's `math*` on each node for UI round-trip; they're ignored at execution time."
        ),
    operator: z.literal('OR').describe('Only `OR` is supported.').default('OR'),
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
            'Custom postfix to add to the aggregation axis, e.g., ` clicks` to format 5 as `5 clicks`. You may need to add a space before postfix. Never set a postfix that `aggregationAxisFormat` already renders: `percentage` and `percentage_scaled` already append the `%` sign, so a `%` postfix would render values as `50%%`.'
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
            'SlopeGraph',
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
    xAxisLabel: z.string().describe('Custom label rendered under the X axis.').optional(),
    yAxisLabel: z.string().describe('Custom label rendered alongside the Y axis.').optional(),
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
    samplingFactor: z.coerce
        .number()
        .nullable()
        .describe('Sampling rate from 0 to 1 where 1 is 100% of the data.')
        .optional(),
    series: z
        .array(z.union([AssistantTrendsEventsNode, AssistantTrendsActionsNode, AssistantTrendsGroupNode]))
        .describe(
            'Events, actions, or groups of events/actions to include. Prioritize the more popular and fresh events and actions.\n\nUse a top-level `EventsNode` or `ActionsNode` entry for each independent series (one line per entry on the chart). Use an `AssistantTrendsGroupNode` to combine multiple events or actions into a single series joined by `OR` — for example, treating "Pageview OR Pageleave" as one line. Only `OR` grouping is supported; pick groups only when the user wants the events counted together, otherwise prefer separate series.'
        ),
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
    optionalInFunnel: z.coerce
        .boolean()
        .describe(
            "If true, this step can be skipped without breaking the funnel — conversion between the surrounding required steps still counts even if this step didn't happen. Set this when the user asks for a non-required, skippable, or optional step in the funnel. Do not set it on the first or last step (those must be required)."
        )
        .default(false)
        .optional(),
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
    optionalInFunnel: z.coerce
        .boolean()
        .describe(
            "If true, this step can be skipped without breaking the funnel — conversion between the surrounding required steps still counts even if this step didn't happen. Set this when the user asks for a non-required, skippable, or optional step in the funnel. Do not set it on the first or last step (those must be required)."
        )
        .default(false)
        .optional(),
    properties: z.array(AssistantPropertyFilter).optional(),
    version: z.coerce.number().describe('version of the node, used for schema migrations').optional(),
})

const AssistantFunnelsGroupNode = z.object({
    custom_name: z.string().optional(),
    kind: z.literal('GroupNode').default('GroupNode'),
    name: z.string().describe('Display name for the combined step.').optional(),
    nodes: z
        .array(z.union([AssistantFunnelsEventsNode, AssistantFunnelsActionsNode]))
        .min(2)
        .describe(
            'Events and actions combined into the step. Use per-node `properties` to filter each event; there is no step-wide filter on a grouped step.'
        ),
    operator: z.literal('OR').describe('Only `OR` is supported.').default('OR'),
})

const AssistantFunnelsNode = z.union([
    AssistantFunnelsEventsNode,
    AssistantFunnelsActionsNode,
    AssistantFunnelsGroupNode,
])

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
    samplingFactor: z.coerce
        .number()
        .nullable()
        .describe('Sampling rate from 0 to 1 where 1 is 100% of the data.')
        .optional(),
    series: z
        .array(AssistantFunnelsNode)
        .describe('Events or actions to include. Prioritize the more popular and fresh events and actions.'),
})

const RetentionPeriod = z.enum(['Hour', 'Day', 'Week', 'Month'])

const RetentionType = z.enum(['retention_recurring', 'retention_first_time', 'retention_first_ever_occurrence'])

const AssistantRetentionEventsNode = z.object({
    custom_name: z.string().describe('Custom name for the event if it is needed to be renamed.').optional(),
    id: z
        .string()
        .describe(
            'The event name from the plan as a string. This is the field the retention query engine uses to match events, so it must be populated exactly as the event appears in the plan. For actions use `AssistantRetentionActionsNode` instead, where `id` is the numeric action ID.'
        ),
    name: z
        .string()
        .describe(
            'Optional human-readable label for the event, used for display only. Defaults to `id` if omitted and is never used for event matching.'
        )
        .optional(),
    properties: z.array(AssistantPropertyFilter).describe('Property filters for the event.').optional(),
    type: z.literal('events').default('events'),
})

const AssistantRetentionActionsNode = z.object({
    id: z.coerce
        .number()
        .describe(
            'The numeric action ID from the plan. This is the field the retention query engine uses to look up the action definition. For events use `AssistantRetentionEventsNode` instead, where `id` is the event name string.'
        ),
    name: z
        .string()
        .describe(
            "Optional human-readable label for the action, used for display only. Defaults to the action's stored name if omitted and is never used for action matching."
        )
        .optional(),
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
        .enum(['event', 'person', 'data_warehouse'])
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
        .max(31)
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
    samplingFactor: z.coerce
        .number()
        .nullable()
        .describe('Sampling rate from 0 to 1 where 1 is 100% of the data.')
        .optional(),
})

const AssistantStickinessEventsNode = z.object({
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
    properties: z.array(AssistantPropertyFilter).optional(),
})

const AssistantStickinessActionsNode = z.object({
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
    properties: z.array(AssistantPropertyFilter).optional(),
})

const AssistantStickinessNode = z.union([AssistantStickinessEventsNode, AssistantStickinessActionsNode])

const StickinessComputationMode = z.enum(['non_cumulative', 'cumulative'])

const AssistantStickinessDisplayType = z.enum(['ActionsLineGraph', 'ActionsBar', 'ActionsAreaGraph'])

const StickinessOperator = z.enum(['gte', 'lte', 'exact'])

const positive_integer = z.coerce.number().int()

const StickinessCriteria = z.object({
    operator: StickinessOperator,
    value: positive_integer,
})

const AssistantStickinessFilter = z.object({
    computedAs: StickinessComputationMode.describe(
        'Computation mode. `non_cumulative` (default) shows users active on exactly N intervals. `cumulative` shows users active on N or more intervals.'
    )
        .default('non_cumulative')
        .optional(),
    display: AssistantStickinessDisplayType.describe(
        'Visualization type for the stickiness chart. `ActionsLineGraph` - line chart (default). `ActionsBar` - bar chart. `ActionsAreaGraph` - area chart.'
    )
        .default('ActionsLineGraph')
        .optional(),
    showLegend: z.coerce.boolean().describe('Whether to show the legend describing series.').default(false).optional(),
    showValuesOnSeries: z.coerce
        .boolean()
        .describe('Whether to show a value on each data point.')
        .default(false)
        .optional(),
    stickinessCriteria: StickinessCriteria.describe(
        'Filter which intervals count based on event frequency within each interval. For example, only count intervals where the user performed the event >= 3 times.'
    ).optional(),
})

const AssistantStickinessQuery = z.object({
    aggregation_group_type_index: z.union([integer, z.null()]).describe('Groups aggregation').optional(),
    compareFilter: CompareFilter.describe(
        'Compare to date range. When enabled, shows the current and previous period side by side.'
    ).optional(),
    dateRange: AssistantDateRangeFilter.describe('Date range for the query').optional(),
    filterTestAccounts: z.coerce
        .boolean()
        .describe('Exclude internal and test users by applying the respective filters')
        .default(false)
        .optional(),
    interval: IntervalType.describe(
        'Granularity of the response. Can be one of `hour`, `day`, `week` or `month`. This determines what counts as one "interval" for stickiness measurement. For example, with `day` interval over a 30-day range, the X-axis shows 1 through 30 days, and each bar/point shows how many users performed the event on exactly that many days.'
    )
        .default('day')
        .optional(),
    intervalCount: integer
        .describe(
            'How many base intervals comprise one stickiness period. Defaults to 1. For example, `interval: "day"` with `intervalCount: 7` groups by 7-day periods.'
        )
        .optional(),
    kind: z.literal('StickinessQuery').default('StickinessQuery'),
    properties: z.array(AssistantPropertyFilter).describe('Property filters for all series').default([]).optional(),
    samplingFactor: z.coerce
        .number()
        .nullable()
        .describe('Sampling rate from 0 to 1 where 1 is 100% of the data.')
        .optional(),
    series: z
        .array(AssistantStickinessNode)
        .describe(
            'Events or actions to include. Each series measures how many intervals (e.g. days) within the date range a user performed the event. Prioritize the more popular and fresh events and actions. When the `math` field is omitted on a series, it defaults to counting unique persons.'
        ),
    stickinessFilter: AssistantStickinessFilter.describe('Properties specific to the stickiness insight').optional(),
})

const PathType = z.enum(['$pageview', '$screen', 'custom_event', 'hogql'])

const AssistantPathCleaningFilter = z.object({
    alias: z
        .string()
        .describe(
            'A human-readable alias that replaces matched path patterns in the visualization. For example, `/user/:id/profile` to replace `/user/123/profile`. Uses ClickHouse `replaceRegexpAll` replacement syntax — use `\\\\1` for capture group back-references.'
        ),
    regex: z
        .string()
        .describe(
            'A ClickHouse regex pattern to match against path values. Matched paths will be replaced with the alias. For example, `\\/user\\/\\d+\\/profile` to match any user profile URL.'
        ),
})

const AssistantPathsFilter = z.object({
    edgeLimit: integer
        .describe(
            'Maximum number of path edges (connections between steps) to return. Higher values show more detail but can make the visualization harder to read.'
        )
        .default(50)
        .optional(),
    endPoint: z
        .string()
        .describe('Filter to only show paths that end at this specific step. Same format as `startPoint`.')
        .optional(),
    excludeEvents: z
        .array(z.string())
        .describe(
            'Event names or URLs to exclude from the path analysis entirely. Excluded events are filtered out before building the path visualization. Useful for removing noise from common but uninteresting events.'
        )
        .default([])
        .optional(),
    includeEventTypes: z
        .array(PathType)
        .describe(
            'Which event types to include in the path analysis. Available values: `$pageview` - web page views. Path values are page URLs (from `$current_url`), with trailing slashes stripped. `$screen` - mobile screen views. Path values are screen names (from `$screen_name`). `custom_event` - custom events (any event not starting with `$`). Path values are event names. `hogql` - custom HogQL expression defined in `pathsHogQLExpression`. Path values come from evaluating the expression. You can combine multiple types. If not specified, all events are included without type filtering.'
        )
        .optional(),
    localPathCleaningFilters: z
        .array(AssistantPathCleaningFilter)
        .describe(
            'ClickHouse regex-based rules to clean and normalize path values at the query level. Each rule applies `replaceRegexpAll(path, regex, alias)` in sequence. Useful for removing dynamic IDs or parameters from URLs.'
        )
        .default([])
        .optional(),
    maxEdgeWeight: integer
        .describe(
            'Maximum number of users who traversed an edge for it to be displayed. Filters out high-traffic paths to focus on less common journeys.'
        )
        .optional(),
    minEdgeWeight: integer
        .describe(
            'Minimum number of users who traversed an edge for it to be displayed. Filters out low-traffic paths to reduce visual noise.'
        )
        .optional(),
    pathDropoffKey: z
        .string()
        .describe(
            'Actors drilldown only. Restrict the returned persons to those who **dropped off** at a specific node (reached it but did not continue). Format is `<stepIndex>_<value>`. Mutually exclusive with `pathStartKey` / `pathEndKey`. Ignored by non-actors paths queries.'
        )
        .optional(),
    pathEndKey: z
        .string()
        .describe(
            'Actors drilldown only. Restrict the returned persons to those who **arrived at** a specific node in the path graph. Format is `<stepIndex>_<value>`, e.g. `"3_https://example.com/checkout"`. Take the value verbatim from a `target` field of a `query-paths` result row. Combine with `pathStartKey` to pin a single edge. Leave unset to return every actor on the path. Ignored by non-actors paths queries.'
        )
        .optional(),
    pathGroupings: z
        .array(z.string())
        .describe(
            'Glob-like patterns to group multiple path items into a single step. Use `*` as a wildcard. The patterns are auto-escaped, so only `*` has special meaning. For example, `/product/*` to group all product pages into one node.'
        )
        .default([])
        .optional(),
    pathStartKey: z
        .string()
        .describe(
            'Actors drilldown only. Restrict the returned persons to those who **departed from** a specific node in the path graph. Format is `<stepIndex>_<value>`, e.g. `"2_https://example.com/pricing"`. Take the value verbatim from a `source` field of a `query-paths` result row. Combine with `pathEndKey` to pin a single edge (source → target). Leave unset to return every actor on the path (constrained only by `startPoint` / `endPoint`). Ignored by non-actors paths queries.'
        )
        .optional(),
    pathsHogQLExpression: z
        .string()
        .describe(
            'A HogQL expression to use as the path item. Required when `hogql` is included in `includeEventTypes`. For example, `properties.$current_url` to use the current URL as the path item.'
        )
        .optional(),
    startPoint: z
        .string()
        .describe(
            'Filter to only show paths that start from this specific step. The value format depends on the included event types: For `$pageview` paths, use page URLs like `/login` or `/dashboard`. For `$screen` paths, use screen names. For `custom_event` paths, use event names.'
        )
        .optional(),
    stepLimit: integer
        .describe(
            'Maximum number of steps (path depth) to show in the visualization. Controls how deep the path analysis goes from the start.'
        )
        .default(5)
        .optional(),
})

const AssistantPathsQuery = z.object({
    aggregation_group_type_index: z.union([integer, z.null()]).describe('Groups aggregation').optional(),
    dateRange: AssistantDateRangeFilter.describe('Date range for the query').optional(),
    filterTestAccounts: z.coerce
        .boolean()
        .describe('Exclude internal and test users by applying the respective filters')
        .default(false)
        .optional(),
    kind: z.literal('PathsQuery').default('PathsQuery'),
    pathsFilter: AssistantPathsFilter.describe(
        'Properties specific to the paths insight. Paths show the most common sequences of events or pages that users navigate through, helping identify popular user flows and drop-off points.'
    ),
    properties: z.array(AssistantPropertyFilter).describe('Property filters for all series').default([]).optional(),
    samplingFactor: z.coerce
        .number()
        .nullable()
        .describe('Sampling rate from 0 to 1 where 1 is 100% of the data.')
        .optional(),
})

const LifecycleToggle = z.enum(['new', 'resurrecting', 'returning', 'dormant'])

const AssistantLifecycleFilter = z.object({
    showLegend: z.coerce.boolean().describe('Whether to show the legend describing series.').default(false).optional(),
    showValuesOnSeries: z.coerce
        .boolean()
        .describe('Whether to show a value on each data point.')
        .default(false)
        .optional(),
    stacked: z.coerce.boolean().describe('Whether the lifecycle bars should be stacked.').default(true).optional(),
    toggledLifecycles: z
        .array(LifecycleToggle)
        .describe(
            'Lifecycles that have been removed from display are not included in this array. Available values: `new`, `returning`, `resurrecting`, `dormant`.\n- `new` - users who performed the event for the first time during the period.\n- `returning` - users who were active in the previous period and are active in the current period.\n- `resurrecting` - users who were inactive for one or more periods and became active again.\n- `dormant` - users who were active in the previous period but are inactive in the current period.'
        )
        .optional(),
})

const AssistantLifecycleEventsNode = z.object({
    custom_name: z.string().optional(),
    event: z.string().nullable().describe('The event or `null` for all events.').optional(),
    kind: z
        .literal('EventsNode')
        .describe('Defines the event series for the lifecycle insight. Lifecycle does not support math aggregations.')
        .default('EventsNode'),
    name: z.string().optional(),
    properties: z.array(AssistantPropertyFilter).optional(),
})

const AssistantLifecycleActionsNode = z.object({
    custom_name: z.string().optional(),
    id: integer,
    kind: z
        .literal('ActionsNode')
        .describe(
            'Defines the action series for the lifecycle insight. Lifecycle does not support math aggregations. You must provide the action ID in the `id` field and the name in the `name` field.'
        )
        .default('ActionsNode'),
    name: z.string().describe('Action name from the plan.'),
    properties: z.array(AssistantPropertyFilter).optional(),
})

const AssistantLifecycleSeriesNode = z.union([AssistantLifecycleEventsNode, AssistantLifecycleActionsNode])

const AssistantLifecycleQuery = z.object({
    aggregation_group_type_index: z.union([integer, z.null()]).describe('Groups aggregation').optional(),
    dateRange: AssistantDateRangeFilter.describe('Date range for the query').optional(),
    filterTestAccounts: z.coerce
        .boolean()
        .describe('Exclude internal and test users by applying the respective filters')
        .default(false)
        .optional(),
    interval: IntervalType.describe('Granularity of the response. Can be one of `hour`, `day`, `week` or `month`')
        .default('day')
        .optional(),
    kind: z.literal('LifecycleQuery').default('LifecycleQuery'),
    lifecycleFilter: AssistantLifecycleFilter.describe('Properties specific to the lifecycle insight').optional(),
    properties: z.array(AssistantPropertyFilter).describe('Property filters for all series').default([]).optional(),
    samplingFactor: z.coerce
        .number()
        .nullable()
        .describe('Sampling rate from 0 to 1 where 1 is 100% of the data.')
        .optional(),
    series: z
        .array(AssistantLifecycleSeriesNode)
        .max(1)
        .describe('Event or action to analyze. Lifecycle insights only support a single series.'),
})

const AssistantInsightVizNode = z.object({
    kind: z.literal('InsightVizNode').default('InsightVizNode'),
    source: z
        .union([
            AssistantTrendsQuery,
            AssistantFunnelsQuery,
            AssistantRetentionQuery,
            AssistantStickinessQuery,
            AssistantPathsQuery,
            AssistantLifecycleQuery,
        ])
        .describe(
            'Product analytics query object. The `kind` field selects the query type and the display/filter options valid for it.'
        ),
})

const AssistantDataVisualizationGoalLine = z.object({
    label: z.string().describe('Label rendered next to the goal line.'),
    value: z.coerce.number().describe('Y-axis value at which the goal line is drawn.'),
})

const AssistantDataVisualizationYAxisSettings = z.object({
    label: z.string().describe('Label rendered beside this Y axis.').optional(),
    scale: z.enum(['linear', 'logarithmic']).describe('Scale used for this Y axis.').optional(),
    showGridLines: z.coerce.boolean().describe('Show grid lines for this Y axis.').optional(),
    showTicks: z.coerce.boolean().describe('Show tick labels on this Y axis.').optional(),
    startAtZero: z.coerce.boolean().describe('Whether this Y axis should start at zero.').optional(),
})

const AssistantDataVisualizationAxisDisplaySettings = z.object({
    color: z.string().describe('Custom color for this series as a hex string (e.g. `#1d4aff`).').optional(),
    displayType: z
        .enum(['auto', 'line', 'bar', 'area'])
        .describe(
            'Override how this individual series is rendered, independent of the chart-level `display` type. Use this to mix series types — e.g. plot one series as `bar` and overlay another as `line`. `auto` follows the chart-level display type.'
        )
        .optional(),
    label: z
        .string()
        .describe('Custom label for this series, shown in the legend and tooltips instead of the column name.')
        .optional(),
    trendLine: z.coerce
        .boolean()
        .describe('Draw a linear trend line for this series. Only meaningful for line, bar, and area charts.')
        .optional(),
    yAxisPosition: z
        .enum(['left', 'right'])
        .describe('Which Y axis this numeric series should use. Use `right` for a secondary Y axis.')
        .optional(),
})

const AssistantDataVisualizationAxisFormatting = z.object({
    decimalPlaces: z.coerce.number().describe('Number of decimal places to display.').optional(),
    prefix: z.string().describe('Text prepended to each value (e.g. `$`).').optional(),
    style: z
        .enum(['none', 'number', 'short', 'percent'])
        .describe(
            'Number formatting style.\n- `none` — no formatting.\n- `number` — thousands separators (e.g. `1,234`).\n- `short` — abbreviated large numbers (e.g. `1.2k`, `3.4M`).\n- `percent` — render the value as a percentage.'
        )
        .optional(),
    suffix: z.string().describe('Text appended to each value (e.g. `%` or ` ms`).').optional(),
})

const AssistantDataVisualizationAxisSettings = z.object({
    display: AssistantDataVisualizationAxisDisplaySettings.describe(
        'Display settings for a plotted Y series.'
    ).optional(),
    formatting: AssistantDataVisualizationAxisFormatting.describe(
        'Number-formatting settings for the values on this axis or series.'
    ).optional(),
})

const AssistantDataVisualizationAxis = z.object({
    column: z.string().describe('Name of a column returned by the SQL query to map onto this axis.'),
    settings: AssistantDataVisualizationAxisSettings.describe(
        'Optional series settings. Only applies to Y-axis series.'
    ).optional(),
})

const AssistantDataVisualizationChartSettings = z.object({
    goalLines: z
        .array(AssistantDataVisualizationGoalLine)
        .describe('Horizontal goal lines drawn across the chart.')
        .optional(),
    leftYAxisSettings: AssistantDataVisualizationYAxisSettings.describe('Settings for the left Y axis.').optional(),
    rightYAxisSettings: AssistantDataVisualizationYAxisSettings.describe(
        'Settings for the right Y axis. Only applies when a Y series uses `settings.display.yAxisPosition: "right"`.'
    ).optional(),
    seriesBreakdownColumn: z
        .string()
        .nullable()
        .describe(
            'Column that splits a single Y series into multiple colored series — e.g. breaking down a line chart by `country`. Set to `null` or omit to disable.'
        )
        .optional(),
    showLegend: z.coerce.boolean().describe('Show the chart legend.').optional(),
    showNullsAsZero: z.coerce.boolean().describe('Replace null aggregation results with zero.').optional(),
    showValuesOnSeries: z.coerce
        .boolean()
        .describe("Render each data point's value as a label directly on the series.")
        .optional(),
    stackBars100: z.coerce
        .boolean()
        .describe('Stack bars to 100% of the total. Only meaningful with `ActionsStackedBar`.')
        .optional(),
    xAxis: AssistantDataVisualizationAxis.describe(
        'Column used as the X axis. Typically a time bucket or categorical column.'
    ).optional(),
    xAxisLabel: z.string().describe('Label rendered under the X axis.').optional(),
    yAxis: z
        .array(AssistantDataVisualizationAxis)
        .describe('One or more numeric columns plotted as Y series.')
        .optional(),
})

const AssistantDataVisualizationDisplayType = z.enum([
    'ActionsTable',
    'BoldNumber',
    'ActionsLineGraph',
    'ActionsBar',
    'ActionsPie',
    'ActionsStackedBar',
    'ActionsAreaGraph',
    'TwoDimensionalHeatmap',
])

const AssistantDataVisualizationTableSettings = z.object({
    columns: z
        .array(AssistantDataVisualizationAxis)
        .describe('Columns to display and their order. Omit to show every column returned by the query.')
        .optional(),
    pinnedColumns: z.array(z.string()).describe('Column names to pin to the left of the table.').optional(),
    showTotalRow: z.coerce.boolean().describe('Show a total row at the bottom of the table.').optional(),
    transpose: z.coerce.boolean().describe('Transpose rows and columns.').optional(),
})

const AssistantDataVisualizationNode = z.object({
    chartSettings: AssistantDataVisualizationChartSettings.describe(
        'Chart configuration. Ignored when `display` is `ActionsTable` or `BoldNumber`.'
    ).optional(),
    display: AssistantDataVisualizationDisplayType.describe(
        'Visualization type. Defaults to `ActionsTable` when omitted.\n\nGuidance:\n- Single-value result (one numeric column, one row) → `BoldNumber`.\n- Time series → `ActionsLineGraph` or `ActionsAreaGraph`.\n- Categorical proportions → `ActionsPie`.\n- Categorical comparison → `ActionsBar` or `ActionsStackedBar`.\n- Two-dimensional aggregation → `TwoDimensionalHeatmap`.\n- Otherwise → `ActionsTable`.'
    ).optional(),
    kind: z.literal('DataVisualizationNode').default('DataVisualizationNode'),
    source: z.record(z.string(), z.unknown()).describe('HogQL query object that produces the rows to visualize.'),
    tableSettings: AssistantDataVisualizationTableSettings.describe(
        'Table configuration. Only applies when `display` is `ActionsTable` or omitted.'
    ).optional(),
})

const InsightQuery = z.union([AssistantInsightVizNode, AssistantDataVisualizationNode])

const InsightCreateSchema = InsightsCreateBody.omit({
    derived_name: true,
    order: true,
    deleted: true,
    _create_in_folder: true,
}).extend({
    query: InsightQuery,
    dashboards: InsightsCreateBody.shape['dashboards'].describe(
        'Dashboard IDs this insight should belong to. This is a full replacement — always include all existing dashboard IDs when adding a new one.'
    ),
})

const insightCreate = (): ToolBase<typeof InsightCreateSchema, WithPostHogUrl<Schemas.Insight>> => ({
    name: 'insight-create',
    schema: InsightCreateSchema,
    handler: async (context: Context, params: z.infer<typeof InsightCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.dashboards !== undefined) {
            body['dashboards'] = params.dashboards
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.favorited !== undefined) {
            body['favorited'] = params.favorited
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas.Insight>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/`,
            body,
        })
        const filtered = omitResponseFields(result, [
            'result',
            'hasMore',
            'columns',
            'is_cached',
            'query_status',
            'hogql',
            'types',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/insights/${filtered.short_id}`)
    },
})

const InsightDeleteSchema = InsightsDestroyParams.omit({ project_id: true })

const insightDelete = (): ToolBase<typeof InsightDeleteSchema, Schemas.Insight> => ({
    name: 'insight-delete',
    schema: InsightDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof InsightDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Insight>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const InsightGetSchema = InsightsRetrieveParams.omit({ project_id: true })
    .extend(InsightsRetrieveQueryParams.omit({ format: true, from_dashboard: true, refresh: true }).shape)
    .extend({
        filters_override: z
            .union([z.string(), z.record(z.string(), z.unknown())])
            .optional()
            .describe(
                "Object (or pre-encoded JSON string) to override the insight's filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token."
            ),
        variables_override: z
            .union([z.string(), z.record(z.string(), z.unknown())])
            .optional()
            .describe(
                'Object (or pre-encoded JSON string) to override the insight\'s HogQL variables for this request only (not persisted). Format: {"<variable_id>": {"code_name": "<code_name>", "variableId": "<variable_id>", "value": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `insight-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.'
            ),
    })

const insightGet = (): ToolBase<typeof InsightGetSchema, WithPostHogUrl<Schemas.Insight>> => ({
    name: 'insight-get',
    schema: InsightGetSchema,
    handler: async (context: Context, params: z.infer<typeof InsightGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Insight>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/${encodeURIComponent(String(params.id))}/`,
            query: {
                filters_override: params.filters_override,
                variables_override: params.variables_override,
            },
        })
        const filtered = omitResponseFields(result, [
            'result',
            'hasMore',
            'columns',
            'is_cached',
            'query_status',
            'hogql',
            'types',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/insights/${filtered.short_id}`)
    },
})

const InsightUpdateSchema = InsightsPartialUpdateParams.omit({ project_id: true })
    .extend(
        InsightsPartialUpdateBody.omit({ derived_name: true, order: true, deleted: true, _create_in_folder: true })
            .shape
    )
    .extend({
        query: InsightQuery.optional(),
        dashboards: InsightsPartialUpdateBody.shape['dashboards'].describe(
            'Dashboard IDs this insight should belong to. This is a full replacement — always include all existing dashboard IDs when adding a new one.'
        ),
    })

const insightUpdate = (): ToolBase<typeof InsightUpdateSchema, WithPostHogUrl<Schemas.Insight>> => ({
    name: 'insight-update',
    schema: InsightUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof InsightUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.dashboards !== undefined) {
            body['dashboards'] = params.dashboards
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.favorited !== undefined) {
            body['favorited'] = params.favorited
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas.Insight>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        const filtered = omitResponseFields(result, [
            'result',
            'hasMore',
            'columns',
            'is_cached',
            'query_status',
            'hogql',
            'types',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/insights/${filtered.short_id}`)
    },
})

const InsightsActivityRetrieveSchema = InsightsActivityRetrieveParams.omit({ project_id: true }).extend(
    InsightsActivityRetrieveQueryParams.omit({ format: true }).shape
)

const insightsActivityRetrieve = (): ToolBase<
    typeof InsightsActivityRetrieveSchema,
    WithPostHogUrl<Schemas.ActivityLogPaginatedResponse>
> => ({
    name: 'insights-activity-retrieve',
    schema: InsightsActivityRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof InsightsActivityRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ActivityLogPaginatedResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/${encodeURIComponent(String(params.id))}/activity/`,
            query: {
                limit: params.limit,
                page: params.page,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                omitResponseFields(item, [
                    'detail.changes.*.before',
                    'detail.changes.*.after',
                    'detail.trigger',
                    'detail.type',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/insights')
    },
})

const InsightsAllActivityRetrieveSchema = InsightsAllActivityRetrieveQueryParams.omit({ format: true })

const insightsAllActivityRetrieve = (): ToolBase<
    typeof InsightsAllActivityRetrieveSchema,
    WithPostHogUrl<Schemas.ActivityLogPaginatedResponse>
> => ({
    name: 'insights-all-activity-retrieve',
    schema: InsightsAllActivityRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof InsightsAllActivityRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ActivityLogPaginatedResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/activity/`,
            query: {
                limit: params.limit,
                page: params.page,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                omitResponseFields(item, [
                    'detail.changes.*.before',
                    'detail.changes.*.after',
                    'detail.trigger',
                    'detail.type',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/insights')
    },
})

const InsightsListSchema = InsightsListQueryParams.omit({ format: true, basic: true, refresh: true }).extend({
    limit: z.preprocess(castStringToInt, InsightsListQueryParams.shape['limit']).optional(),
    offset: z.preprocess(castStringToInt, InsightsListQueryParams.shape['offset']).optional(),
})

const insightsList = (): ToolBase<typeof InsightsListSchema, WithPostHogUrl<Schemas.PaginatedInsightList>> => ({
    name: 'insights-list',
    schema: InsightsListSchema,
    handler: async (context: Context, params: z.infer<typeof InsightsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedInsightList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/`,
            query: {
                created_by: params.created_by,
                created_date_from: params.created_date_from,
                created_date_to: params.created_date_to,
                dashboards: params.dashboards,
                date_from: params.date_from,
                date_to: params.date_to,
                favorited: params.favorited,
                insight: params.insight,
                last_viewed_date_from: params.last_viewed_date_from,
                last_viewed_date_to: params.last_viewed_date_to,
                limit: params.limit,
                offset: params.offset,
                saved: params.saved,
                search: params.search,
                short_id: params.short_id,
                tags: params.tags,
                user: params.user,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'short_id',
                    'name',
                    'derived_name',
                    'description',
                    'tags',
                    'favorited',
                    'dashboards',
                    'created_at',
                    'created_by',
                    'last_modified_at',
                    'last_modified_by',
                    'last_viewed_at',
                    'alerts',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/insights/${item.short_id}`))
                ),
            },
            '/insights'
        )
    },
})

const InsightsTrendingRetrieveSchema = InsightsTrendingRetrieveQueryParams.omit({ format: true })

const insightsTrendingRetrieve = (): ToolBase<
    typeof InsightsTrendingRetrieveSchema,
    WithPostHogUrl<Schemas.PaginatedTrendingInsightList>
> => ({
    name: 'insights-trending-retrieve',
    schema: InsightsTrendingRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof InsightsTrendingRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTrendingInsightList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/trending/`,
            query: {
                days: params.days,
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'short_id',
                    'name',
                    'derived_name',
                    'description',
                    'tags',
                    'favorited',
                    'dashboards',
                    'created_at',
                    'created_by',
                    'last_modified_at',
                    'last_modified_by',
                    'last_viewed_at',
                    'view_count',
                    'viewers',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/insights/${item.short_id}`))
                ),
            },
            '/insights'
        )
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'insight-create': insightCreate,
    'insight-delete': insightDelete,
    'insight-get': insightGet,
    'insight-update': insightUpdate,
    'insights-activity-retrieve': insightsActivityRetrieve,
    'insights-all-activity-retrieve': insightsAllActivityRetrieve,
    'insights-list': insightsList,
    'insights-trending-retrieve': insightsTrendingRetrieve,
}
