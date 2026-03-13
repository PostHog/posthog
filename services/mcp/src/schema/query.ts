import { z } from 'zod'

// Common enums and types
const NodeKind = z.enum(['TrendsQuery', 'FunnelsQuery', 'PathsQuery', 'HogQLQuery', 'EventsNode'])

const IntervalType = z.enum(['hour', 'day', 'week', 'month'])

const ChartDisplayType = z.enum([
    'ActionsLineGraph',
    'ActionsTable',
    'ActionsPie',
    'ActionsBar',
    'ActionsBarValue',
    'WorldMap',
    'BoldNumber',
])

// NOTE: Breakdowns are restricted to either person or event for simplicity
const BreakdownType = z.enum(['person', 'event'])

const FunnelVizType = z.enum(['steps', 'time_to_convert', 'trends'])

const FunnelOrderType = z.enum(['ordered', 'unordered', 'strict'])

const FunnelStepReference = z.enum(['total', 'previous'])

const BreakdownAttributionType = z.enum(['first_touch', 'last_touch', 'all_events'])

const FunnelLayout = z.enum(['horizontal', 'vertical'])

const FunnelConversionWindowTimeUnit = z.enum(['minute', 'hour', 'day', 'week', 'month'])

// Base schemas
const DateRange = z.object({
    date_from: z.string().nullable().optional(),
    date_to: z.string().nullable().optional(),
    explicitDate: z.boolean().optional(),
})

const PropertyFilter = z.object({
    key: z.string(),
    value: z
        .union([z.string(), z.number(), z.array(z.string()), z.array(z.number())])
        .nullable()
        .optional(),
    operator: z.string().optional(),
    type: z.string().optional(),
})

// NOTE: Only a single level of nesting is supported here, since we can't specify recursive schema for tool inputs.
const PropertyGroupFilter = z.object({
    type: z.enum(['AND', 'OR']),
    values: z.array(PropertyFilter),
})

const AnyPropertyFilter = z.union([PropertyFilter, PropertyGroupFilter])

const HogQLVariable = z.object({
    variableId: z.string(),
    code_name: z.string(),
    value: z.any().optional(),
    isNull: z.boolean().optional(),
})

const HogQLFilters = z.object({
    properties: z.array(AnyPropertyFilter).optional(),
    dateRange: DateRange.optional(),
    filterTestAccounts: z.boolean().optional(),
})

// Math types that don't require a property
const BaseMathType = z.enum([
    'total',
    'dau',
    'weekly_active',
    'monthly_active',
    'unique_session',
    'first_time_for_user',
    'first_matching_event_for_user',
])

// Math types that require a math_property
const PropertyMathType = z.enum(['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99'])

// Combined math types
const MathType = z.union([BaseMathType, PropertyMathType])

const PROPERTY_MATH_TYPES = ['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99']

// Base entity object without refinement for extension
const BaseEntityObject = z.object({
    custom_name: z.string().describe('A display name'),
    math: MathType.optional(),
    math_property: z.string().optional(),
    properties: z.union([z.array(AnyPropertyFilter), PropertyGroupFilter]).optional(),
})

const EventsNode = BaseEntityObject.extend({
    kind: z.literal('EventsNode'),
    event: z.string().optional(),
    limit: z.number().optional(),
}).refine(
    (data) => {
        if (PROPERTY_MATH_TYPES.includes(data.math || '')) {
            return !!data.math_property
        }
        return true
    },
    {
        message: `math_property is required for ${PROPERTY_MATH_TYPES.join(', ')} math types`,
    }
)

const AnyEntityNode = EventsNode

// Base query interface
const InsightsQueryBase = z.object({
    dateRange: DateRange.optional(),
    filterTestAccounts: z.boolean().optional().default(false),
    properties: z
        .union([z.array(AnyPropertyFilter), PropertyGroupFilter])
        .optional()
        .default([]),
})

// Breakdown filter
const BreakdownFilter = z.object({
    breakdown_type: BreakdownType.nullable().optional().default('event'),
    breakdown_limit: z.number().optional(),
    breakdown: z
        .union([z.string(), z.number(), z.array(z.union([z.string(), z.number()]))])
        .nullable()
        .optional(),
})

// Compare filter
const CompareFilter = z.object({
    compare: z.boolean().optional().default(false),
    compare_to: z.string().optional(),
})

// Trends filter
const TrendsFilter = z.object({
    display: ChartDisplayType.optional().default('ActionsLineGraph'),
    showLegend: z.boolean().optional().default(false),
})

// Trends query
const TrendsQuerySchema = InsightsQueryBase.extend({
    kind: z.literal('TrendsQuery'),
    interval: IntervalType.optional().default('day'),
    series: z.array(AnyEntityNode),
    trendsFilter: TrendsFilter.optional(),
    breakdownFilter: BreakdownFilter.optional(),
    compareFilter: CompareFilter.optional(),
    conversionGoal: z.any().nullable().optional(),
})

// HogQL query
const HogQLQuerySchema = z.object({
    kind: z.literal('HogQLQuery'),
    query: z.string(),
    filters: HogQLFilters.optional(),
})

// Chart settings for DataVisualizationNode
const DataVizDisplayType = z.enum(['auto', 'line', 'bar'])

const YAxisPosition = z.enum(['left', 'right'])

const ChartSettingsDisplay = z.object({
    color: z.string().nullable().optional(),
    displayType: DataVizDisplayType.nullable().optional(),
    label: z.string().nullable().optional(),
    trendLine: z.boolean().nullable().optional(),
    yAxisPosition: YAxisPosition.nullable().optional(),
})

const FormattingStyle = z.enum(['none', 'number', 'percent'])

const ChartSettingsFormatting = z.object({
    decimalPlaces: z.number().nullable().optional(),
    prefix: z.string().nullable().optional(),
    style: FormattingStyle.nullable().optional(),
    suffix: z.string().nullable().optional(),
})

const ChartAxisSettings = z.object({
    display: ChartSettingsDisplay.nullable().optional(),
    formatting: ChartSettingsFormatting.nullable().optional(),
})

const ChartAxis = z.object({
    column: z.string(),
    settings: ChartAxisSettings.nullable().optional(),
})

const AxisScale = z.enum(['linear', 'logarithmic'])

const YAxisSettings = z.object({
    scale: AxisScale.nullable().optional(),
    showGridLines: z.boolean().nullable().optional(),
    showTicks: z.boolean().nullable().optional(),
    startAtZero: z.boolean().nullable().optional(),
})

const GoalLine = z.object({
    label: z.string(),
    value: z.number(),
    borderColor: z.string().optional(),
    displayLabel: z.boolean().optional(),
    displayIfCrossed: z.boolean().optional(),
    position: z.enum(['start', 'end']).optional(),
})

const DataVizChartSettings = z.object({
    goalLines: z.array(GoalLine).nullable().optional(),
    leftYAxisSettings: YAxisSettings.nullable().optional(),
    rightYAxisSettings: YAxisSettings.nullable().optional(),
    seriesBreakdownColumn: z.string().nullable().optional(),
    showLegend: z.boolean().nullable().optional(),
    showTotalRow: z.boolean().nullable().optional(),
    showXAxisBorder: z.boolean().nullable().optional(),
    showXAxisTicks: z.boolean().nullable().optional(),
    showYAxisBorder: z.boolean().nullable().optional(),
    stackBars100: z.boolean().nullable().optional(),
    xAxis: ChartAxis.nullable().optional(),
    yAxis: z.array(ChartAxis).nullable().optional(),
    yAxisAtZero: z.boolean().nullable().optional(),
    heatmap: z.object({
        colorPalette: z.string().optional(),
        showValues: z.boolean().optional(),
    }).nullable().optional(),
})

const ConditionalFormattingRule = z.object({
    id: z.string(),
    templateId: z.string(),
    columnName: z.string(),
    bytecode: z.array(z.any()),
    input: z.string(),
    color: z.string(),
    colorMode: z.enum(['light', 'dark']).optional(),
})

const DataVizTableSettings = z.object({
    columns: z.array(ChartAxis).nullable().optional(),
    conditionalFormatting: z.array(ConditionalFormattingRule).nullable().optional(),
    pinnedColumns: z.array(z.string()).nullable().optional(),
})

// Funnels filter
const FunnelsFilter = z.object({
    layout: FunnelLayout.optional(),
    breakdownAttributionType: BreakdownAttributionType.optional(),
    breakdownAttributionValue: z.number().optional(),
    funnelToStep: z.number().optional(),
    funnelFromStep: z.number().optional(),
    funnelOrderType: FunnelOrderType.optional(),
    funnelVizType: FunnelVizType.optional(),
    funnelWindowInterval: z.number().optional().default(14),
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.optional().default('day'),
    funnelStepReference: FunnelStepReference.optional(),
})

// Funnels query
const FunnelsQuerySchema = InsightsQueryBase.extend({
    kind: z.literal('FunnelsQuery'),
    interval: IntervalType.optional(),
    series: z.array(AnyEntityNode).min(2, 'At least two steps are required for a funnel'),
    funnelsFilter: FunnelsFilter.optional(),
    breakdownFilter: BreakdownFilter.optional(),
})

// Paths types
const PathType = z.enum(['$pageview', '$screen', 'custom_event', 'hogql'])

const PathCleaningFilter = z.object({
    alias: z.string().optional(),
    regex: z.string().optional(),
})

// Paths filter
const PathsFilter = z.object({
    includeEventTypes: z.array(PathType).optional(),
    pathsHogQLExpression: z
        .string()
        .optional()
        .describe('A HogQL expression to use as the path step name. Requires includeEventTypes to contain "hogql".'),
    startPoint: z.string().optional().describe('Only show paths starting at this step'),
    endPoint: z.string().optional().describe('Only show paths ending at this step'),
    stepLimit: z.number().optional().default(5).describe('Maximum number of path steps (default 5)'),
    edgeLimit: z.number().optional().default(50).describe('Maximum number of edges to return (default 50)'),
    excludeEvents: z.array(z.string()).optional().describe('Events to exclude from the path'),
    pathGroupings: z.array(z.string()).optional().describe('Wildcard groups to merge similar path steps'),
    localPathCleaningFilters: z
        .array(PathCleaningFilter)
        .optional()
        .describe('Regex rules to clean/simplify path step names'),
    minEdgeWeight: z.number().optional(),
    maxEdgeWeight: z.number().optional(),
})

// Paths query
const PathsQuerySchema = InsightsQueryBase.extend({
    kind: z.literal('PathsQuery'),
    pathsFilter: PathsFilter.default({ stepLimit: 5, edgeLimit: 50 }),
})

// Insight Schema
const InsightVizNodeSchema = z.object({
    kind: z.literal('InsightVizNode'),
    source: z.discriminatedUnion('kind', [TrendsQuerySchema, FunnelsQuerySchema, PathsQuerySchema]),
})

const DataVisualizationNodeSchema = z.object({
    kind: z.literal('DataVisualizationNode'),
    source: HogQLQuerySchema,
    chartSettings: DataVizChartSettings.optional().describe(
        'Chart visualization settings including axis configuration. Use xAxis to set X-axis column, yAxis array to set Y-axis columns with optional display type (line/bar/auto).'
    ),
    tableSettings: DataVizTableSettings.optional().describe(
        'Table display settings including column configuration and conditional formatting.'
    ),
})

// Any insight query
const InsightQuerySchema = z.discriminatedUnion('kind', [InsightVizNodeSchema, DataVisualizationNodeSchema])

// Export all schemas
export {
    // Enums
    NodeKind,
    IntervalType,
    ChartDisplayType,
    BreakdownType,
    FunnelVizType,
    FunnelOrderType,
    FunnelStepReference,
    BreakdownAttributionType,
    FunnelLayout,
    FunnelConversionWindowTimeUnit,
    // Math types
    BaseMathType,
    PropertyMathType,
    MathType,
    // Base types
    DateRange,
    PropertyFilter,
    PropertyGroupFilter,
    AnyPropertyFilter,
    // Entity nodes
    EventsNode,
    AnyEntityNode,
    // Filters
    BreakdownFilter,
    CompareFilter,
    TrendsFilter,
    FunnelsFilter,
    PathsFilter,
    // HogQL types
    HogQLVariable,
    HogQLFilters,
    // Chart settings for DataVisualizationNode
    DataVizChartSettings,
    DataVizTableSettings,
    ChartAxis,
    // Queries
    TrendsQuerySchema,
    FunnelsQuerySchema,
    PathsQuerySchema,
    HogQLQuerySchema,
    InsightVizNodeSchema,
    DataVisualizationNodeSchema,
    InsightQuerySchema,
}

export type TrendsQuery = z.infer<typeof TrendsQuerySchema>
export type FunnelsQuery = z.infer<typeof FunnelsQuerySchema>
export type PathsQuery = z.infer<typeof PathsQuerySchema>
export type HogQLQuery = z.infer<typeof HogQLQuerySchema>
export type InsightQuery = z.infer<typeof InsightQuerySchema>
