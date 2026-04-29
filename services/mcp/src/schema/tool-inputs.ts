import { z } from 'zod'

import { DataVisualizationNodeSchema, HogQLQuerySchema, InsightVizNodeSchema, PropertyFilter } from './query'

export const ExternalDataJobsAfterSchema = z
    .string()
    .describe('ISO timestamp — only return jobs created after this date (e.g. "2025-01-01T00:00:00Z").')

export const ExternalDataJobsBeforeSchema = z
    .string()
    .describe('ISO timestamp — only return jobs created before this date (e.g. "2025-12-31T23:59:59Z").')

export const ExternalDataJobsSchemasSchema = z
    .array(z.string())
    .describe('Filter jobs by table schema names (e.g. ["users", "orders"]). Only returns jobs for these tables.')

export const ExternalDataSourcePayloadSchema = z
    .record(z.string(), z.unknown())
    .describe(
        'Connection credentials for the source. Keys depend on source_type. For database sources: host, port, database, user, password, schema. For SaaS sources: api_key or OAuth fields. Use external-data-sources-wizard to see required fields per source type.'
    )

export const ExternalDataSourceTypeSchema = z
    .string()
    .describe(
        'The source type name (e.g. "Postgres", "MySQL", "Stripe"). Use external-data-sources-wizard to see available types and their required fields.'
    )

export const PromptListInputSchema = z.object({
    search: z.string().optional().describe('Optional substring filter applied to prompt names and prompt content.'),
    content: z
        .enum(['full', 'preview', 'none'])
        .default('none')
        .describe(
            "Controls how much prompt content is included in list results. 'full' includes the full prompt, 'preview' includes a short prompt_preview, and 'none' omits prompt content entirely."
        ),
})

export const DocumentationSearchSchema = z.object({
    query: z.string(),
})

export const ExperimentResultsGetSchema = z.object({
    id: z.number().describe('The ID of the experiment to get comprehensive results for'),
    refresh: z
        .boolean()
        .optional()
        .default(false)
        .describe('Force refresh of results instead of using cached values. Defaults to false.'),
})

/**
 * User-friendly input schema for experiment updates
 * This provides a simplified interface that gets transformed to API format
 */
export const ExperimentUpdateInputSchema = z.object({
    name: z.string().optional().describe('Update experiment name'),

    description: z.string().optional().describe('Update experiment description'),

    // Primary metrics with guidance
    primary_metrics: z
        .array(
            z.object({
                name: z.string().optional().describe('Human-readable metric name'),
                metric_type: z
                    .enum(['mean', 'funnel', 'ratio'])
                    .describe(
                        "Metric type: 'mean' for average values, 'funnel' for conversion flows, 'ratio' for comparing two metrics"
                    ),
                event_name: z.string().describe("PostHog event name (e.g., '$pageview', 'add_to_cart', 'purchase')"),
                funnel_steps: z
                    .array(z.string())
                    .optional()
                    .describe('For funnel metrics only: Array of event names for each funnel step'),
                properties: z
                    .array(PropertyFilter)
                    .optional()
                    .describe(
                        'Event property filters as an array, e.g. [{ key: "$browser", value: "Chrome", operator: "exact", type: "event" }]'
                    ),
                description: z.string().optional().describe('What this metric measures'),
            })
        )
        .optional()
        .describe('Update primary metrics'),

    secondary_metrics: z
        .array(
            z.object({
                name: z.string().optional().describe('Human-readable metric name'),
                metric_type: z.enum(['mean', 'funnel', 'ratio']).describe('Metric type'),
                event_name: z.string().describe('PostHog event name'),
                funnel_steps: z.array(z.string()).optional().describe('For funnel metrics only: Array of event names'),
                properties: z
                    .array(PropertyFilter)
                    .optional()
                    .describe(
                        'Event property filters as an array, e.g. [{ key: "$browser", value: "Chrome", operator: "exact", type: "event" }]'
                    ),
                description: z.string().optional().describe('What this metric measures'),
            })
        )
        .optional()
        .describe('Update secondary metrics'),

    minimum_detectable_effect: z.number().optional().describe('Update minimum detectable effect in percentage'),

    // Experiment state management
    launch: z.boolean().optional().describe('Launch experiment (set start_date) or keep as draft'),

    conclude: z
        .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
        .optional()
        .describe('Conclude experiment with result'),

    conclusion_comment: z.string().optional().describe('Comment about experiment conclusion'),

    restart: z
        .boolean()
        .optional()
        .describe('Restart concluded experiment as draft (clears start_date, end_date, and conclusion)'),

    archive: z.boolean().optional().describe('Archive or unarchive experiment'),
})

export const ExperimentUpdateSchema = z.object({
    experimentId: z.number().describe('The ID of the experiment to update'),
    data: ExperimentUpdateInputSchema.describe('The experiment data to update using user-friendly format'),
})

export const ExperimentCreateSchema = z.object({
    name: z.string().min(1).describe('Experiment name - should clearly describe what is being tested'),

    description: z
        .string()
        .optional()
        .describe(
            'Detailed description of the experiment hypothesis, what changes are being tested, and expected outcomes'
        ),

    feature_flag_key: z
        .string()
        .describe(
            'Feature flag key (letters, numbers, hyphens, underscores only). IMPORTANT: First search for existing feature flags that might be suitable using the feature-flags-get-all tool, then suggest reusing existing ones or creating a new key based on the experiment name'
        ),

    // Primary metrics with guidance
    primary_metrics: z
        .array(
            z.object({
                name: z.string().optional().describe('Human-readable metric name'),
                metric_type: z
                    .enum(['mean', 'funnel', 'ratio'])
                    .describe(
                        "Metric type: 'mean' for average values (revenue, time spent), 'funnel' for conversion flows, 'ratio' for comparing two metrics"
                    ),
                event_name: z
                    .string()
                    .describe(
                        "REQUIRED for metrics to work: PostHog event name (e.g., '$pageview', 'add_to_cart', 'purchase'). For funnels, this is the first step. Use '$pageview' if unsure. Search project-property-definitions tool for available events."
                    ),
                funnel_steps: z
                    .array(z.string())
                    .optional()
                    .describe(
                        "For funnel metrics only: Array of event names for each funnel step (e.g., ['product_view', 'add_to_cart', 'checkout', 'purchase'])"
                    ),
                properties: z
                    .array(PropertyFilter)
                    .optional()
                    .describe(
                        'Event property filters as an array, e.g. [{ key: "$browser", value: "Chrome", operator: "exact", type: "event" }]'
                    ),
                description: z
                    .string()
                    .optional()
                    .describe("What this metric measures and why it's important for the experiment"),
            })
        )
        .optional()
        .describe(
            'Primary metrics to measure experiment success. IMPORTANT: Each metric needs event_name to track data. For funnels, provide funnel_steps array with event names for each step. Ask user what events they track, or use project-property-definitions to find available events.'
        ),

    // Secondary metrics for additional insights
    secondary_metrics: z
        .array(
            z.object({
                name: z.string().optional().describe('Human-readable metric name'),
                metric_type: z
                    .enum(['mean', 'funnel', 'ratio'])
                    .describe(
                        "Metric type: 'mean' for average values, 'funnel' for conversion flows, 'ratio' for comparing two metrics"
                    ),
                event_name: z.string().describe("REQUIRED: PostHog event name. Use '$pageview' if unsure."),
                funnel_steps: z
                    .array(z.string())
                    .optional()
                    .describe('For funnel metrics only: Array of event names for each funnel step'),
                properties: z
                    .array(PropertyFilter)
                    .optional()
                    .describe(
                        'Event property filters as an array, e.g. [{ key: "$browser", value: "Chrome", operator: "exact", type: "event" }]'
                    ),
                description: z.string().optional().describe('What this secondary metric measures'),
            })
        )
        .optional()
        .describe(
            'Secondary metrics to monitor for potential side effects or additional insights. Each metric needs event_name.'
        ),

    // Feature flag variants
    variants: z
        .array(
            z.object({
                key: z.string().describe("Variant key (e.g., 'control', 'variant_a', 'new_design')"),
                name: z.string().optional().describe('Human-readable variant name'),
                split_percent: z
                    .number()
                    .min(0)
                    .max(100)
                    .optional()
                    .describe(
                        'Percentage of traffic allocated to this variant (0-100). All variants must sum to 100. One of split_percent (recommended) or rollout_percentage (deprecated) must be provided per variant.'
                    ),
                rollout_percentage: z
                    .number()
                    .min(0)
                    .max(100)
                    .optional()
                    .describe('Deprecated: use split_percent instead. Accepted for backward compatibility.'),
            })
        )
        .optional()
        .describe(
            'Experiment variants. If not specified, defaults to 50/50 control/test split. Ask user how many variants they need and what each tests'
        ),

    // Experiment parameters
    minimum_detectable_effect: z
        .number()
        .default(30)
        .describe(
            'Minimum detectable effect in percentage. Lower values require more users but detect smaller changes. Suggest 20-30% for most experiments'
        ),

    // Exposure and targeting
    filter_test_accounts: z.boolean().default(true).describe('Whether to filter out internal test accounts'),

    target_properties: z
        .record(z.string(), z.any())
        .optional()
        .describe('Properties to target specific user segments (e.g., country, subscription type)'),

    // Control flags
    draft: z
        .boolean()
        .default(true)
        .describe('Create as draft (true) or launch immediately (false). Recommend draft for review first'),

    holdout_id: z
        .number()
        .optional()
        .describe('Holdout group ID if this experiment should exclude users from other experiments'),

    allow_unknown_events: z
        .boolean()
        .optional()
        .describe(
            'Set to true to skip validation that event names exist in the project. Use when intentionally referencing events that have not been ingested yet.'
        ),
})

export const InsightGenerateHogQLFromQuestionSchema = z.object({
    question: z
        .string()
        .max(1000)
        .describe('Your natural language query describing the SQL insight (max 1000 characters).'),
})

export const InsightQueryInputSchema = z.object({
    insightId: z.string().describe('The insight ID or short_id to run.'),
    output_format: z
        .enum(['optimized', 'json'])
        .optional()
        .default('optimized')
        .describe(
            'Output format. "optimized" returns a human-readable summary from server-side formatters (recommended for analysis). "json" returns the raw query results as JSON.'
        ),
})

export const LLMAnalyticsGetCostsSchema = z.object({
    projectId: z.number().int().positive(),
    days: z.number().optional(),
})

export const OrganizationSetActiveSchema = z.object({
    orgId: z.string(),
})

export const ProjectGetAllSchema = z.object({})

export const ProjectEventDefinitionsSchema = z.object({
    q: z.string().optional().describe('Search query to filter event names. Only use if there are lots of events.'),
    limit: z.number().int().positive().optional(),
    offset: z.number().int().min(0).optional(),
})

export const EventDefinitionUpdateInputSchema = z.object({
    description: z.string().optional().describe('Description explaining when the event is triggered'),
    tags: z
        .array(z.string())
        .optional()
        .describe(
            'Tags to organize events by product area (e.g. "checkout", "onboarding") or user journey stage (e.g. "acquisition", "activation", "monetization", "retention")'
        ),
    verified: z
        .boolean()
        .optional()
        .describe('Mark as verified to indicate the event is properly instrumented and tracking correctly'),
    hidden: z
        .boolean()
        .optional()
        .describe('Mark event as no longer used/captured. Hides it from UI while preserving historical data'),
})

export const EventDefinitionUpdateSchema = z.object({
    eventName: z.string().describe('The name of the event to update (e.g. "$pageview", "user_signed_up")'),
    data: EventDefinitionUpdateInputSchema.describe('The event definition data to update'),
})

export const ProjectPropertyDefinitionsInputSchema = z.object({
    type: z.enum(['event', 'person']).describe('Type of properties to get'),
    eventName: z.string().describe('Event name to filter properties by, required for event type').optional(),
    includePredefinedProperties: z.boolean().optional().describe('Whether to include predefined properties'),
    limit: z.number().int().positive().optional(),
    offset: z.number().int().min(0).optional(),
})

export const ProjectSetActiveSchema = z.object({
    projectId: z.number().int().positive(),
})

export const SurveyResponseCountsSchema = z.object({})

const QueryRunQuerySchema = z.discriminatedUnion('kind', [
    InsightVizNodeSchema,
    DataVisualizationNodeSchema,
    HogQLQuerySchema,
])

export const QueryRunInputSchema = z.object({
    query: QueryRunQuerySchema,
})

export const HogQLSchemaInputSchema = z.object({
    connectionId: z
        .string()
        .optional()
        .describe(
            'Optional id of an external data source (e.g. a Postgres or DuckDB direct-query connection). When set, returns the schema of that source instead of the ClickHouse catalog. Use external-data-sources-list to discover available connection ids.'
        ),
})

export const QueryValidateInputSchema = z.object({
    query: z
        .string()
        .min(1)
        .describe(
            'The HogQL (ClickHouse-flavored SQL) query to validate. Parsed and type-checked without executing, so there is no ClickHouse cost.'
        ),
    language: z
        .enum(['hogQL', 'hogQLExpr', 'hog', 'hogTemplate'])
        .default('hogQL')
        .describe(
            "Language to validate. Defaults to 'hogQL' (full SELECT statements). Use 'hogQLExpr' for a bare expression, 'hog' or 'hogTemplate' for Hog source."
        ),
    connectionId: z
        .string()
        .optional()
        .describe(
            'Optional id of an external data source (e.g. a Postgres or DuckDB direct-query connection). When set, validates against that source instead of the ClickHouse catalog. Use external-data-sources-list to discover available connection ids.'
        ),
})

// Entity Search
export const EntitySearchSchema = z.object({
    query: z.string().min(1).describe('Search query to find entities by name or description'),
    entities: z
        .array(
            z.enum([
                'insight',
                'dashboard',
                'experiment',
                'feature_flag',
                'notebook',
                'action',
                'cohort',
                'event_definition',
                'survey',
            ])
        )
        .optional()
        .describe(
            'Entity types to search. If not specified, searches all types. Available: insight, dashboard, experiment, feature_flag, notebook, action, cohort, event_definition, survey'
        ),
})

// Debug MCP UI Apps
export const DebugMcpUiAppsSchema = z.object({
    message: z.string().optional().describe('Optional message to include in the debug data'),
})

// PostHog AI tools
export const ExecuteSQLSchema = z.object({
    query: z.string().min(1).describe('The final SQL query to be executed.'),
    truncate: z
        .boolean()
        .optional()
        .default(true)
        .describe(
            'Whether to truncate large blob/JSON values in results. Defaults to true. Set to false when you need full untruncated results (e.g., for dumping to a file).'
        ),
})

export const ReadDataWarehouseSchemaSchema = z
    .object({})
    .describe('No input required. Returns core data warehouse schemas.')

const ReadEventsQuerySchema = z.object({
    kind: z.literal('events'),
    limit: z.number().int().min(1).max(500).default(500).optional().describe('Number of events to return per page.'),
    offset: z.number().int().min(0).default(0).optional().describe('Number of events to skip for pagination.'),
})

const ReadEventPropertiesQuerySchema = z.object({
    kind: z.literal('event_properties'),
    event_name: z.string().describe('The name of the event that you want to retrieve properties for.'),
})

const ReadEntityPropertiesQuerySchema = z.object({
    kind: z.literal('entity_properties'),
    entity: z.string().describe('The type of the entity that you want to retrieve properties for.'),
})

const ReadActionPropertiesQuerySchema = z.object({
    kind: z.literal('action_properties'),
    action_id: z.number().int().describe('The ID of the action that you want to retrieve properties for.'),
})

const ReadEntitySamplePropertyValuesQuerySchema = z.object({
    kind: z.literal('entity_property_values'),
    entity: z.string().describe('The type of the entity that you want to retrieve properties for.'),
    property_name: z.string().describe('Verified property name of an entity.'),
})

const ReadEventSamplePropertyValuesQuerySchema = z.object({
    kind: z.literal('event_property_values'),
    event_name: z.string().describe('Verified event name'),
    property_name: z.string().describe('Verified property name of an event.'),
})

const ReadActionSamplePropertyValuesQuerySchema = z.object({
    kind: z.literal('action_property_values'),
    action_id: z.number().int().describe('Verified action ID'),
    property_name: z.string().describe('Verified property name of an action.'),
})

export const ReadDataSchemaSchema = z.object({
    query: z
        .discriminatedUnion('kind', [
            ReadEventsQuerySchema,
            ReadEventPropertiesQuerySchema,
            ReadEntityPropertiesQuerySchema,
            ReadActionPropertiesQuerySchema,
            ReadEntitySamplePropertyValuesQuerySchema,
            ReadEventSamplePropertyValuesQuerySchema,
            ReadActionSamplePropertyValuesQuerySchema,
        ])
        .describe('The data schema query to execute.'),
})
