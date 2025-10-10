import { z } from 'zod'
import {
    AddInsightToDashboardSchema,
    CreateDashboardInputSchema,
    ListDashboardsSchema,
    UpdateDashboardInputSchema,
} from './dashboards'
import { ErrorDetailsSchema, ListErrorsSchema } from './errors'
import { FilterGroupsSchema, UpdateFeatureFlagInputSchema } from './flags'
import { CreateInsightInputSchema, ListInsightsSchema, UpdateInsightInputSchema } from './insights'
import { InsightQuerySchema } from './query'
import {
    CreateSurveyInputSchema,
    GetSurveySpecificStatsInputSchema,
    GetSurveyStatsInputSchema,
    ListSurveysInputSchema,
    UpdateSurveyInputSchema,
} from './surveys'

export const DashboardAddInsightSchema = z.object({
    data: AddInsightToDashboardSchema,
})

export const DashboardCreateSchema = z.object({
    data: CreateDashboardInputSchema,
})

export const DashboardDeleteSchema = z.object({
    dashboardId: z.number(),
})

export const DashboardGetSchema = z.object({
    dashboardId: z.number(),
})

export const DashboardGetAllSchema = z.object({
    data: ListDashboardsSchema.optional(),
})

export const DashboardUpdateSchema = z.object({
    dashboardId: z.number(),
    data: UpdateDashboardInputSchema,
})

export const DocumentationSearchSchema = z.object({
    query: z.string(),
})

export const ErrorTrackingDetailsSchema = ErrorDetailsSchema

export const ErrorTrackingListSchema = ListErrorsSchema

export const ExperimentGetAllSchema = z.object({})

export const ExperimentGetSchema = z.object({
    experimentId: z.number().describe('The ID of the experiment to retrieve'),
})

export const ExperimentResultsGetSchema = z.object({
    experimentId: z.number().describe('The ID of the experiment to get comprehensive results for'),
    refresh: z.boolean().describe('Force refresh of results instead of using cached values'),
})

export const ExperimentDeleteSchema = z.object({
    experimentId: z.number().describe('The ID of the experiment to delete'),
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
                event_name: z
                    .string()
                    .describe("PostHog event name (e.g., '$pageview', 'add_to_cart', 'purchase')"),
                funnel_steps: z
                    .array(z.string())
                    .optional()
                    .describe('For funnel metrics only: Array of event names for each funnel step'),
                properties: z.record(z.any()).optional().describe('Event properties to filter on'),
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
                funnel_steps: z
                    .array(z.string())
                    .optional()
                    .describe('For funnel metrics only: Array of event names'),
                properties: z.record(z.any()).optional().describe('Event properties to filter on'),
                description: z.string().optional().describe('What this metric measures'),
            })
        )
        .optional()
        .describe('Update secondary metrics'),

    minimum_detectable_effect: z
        .number()
        .optional()
        .describe('Update minimum detectable effect in percentage'),

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
        .describe('Restart concluded experiment (clears end_date and conclusion)'),

    archive: z.boolean().optional().describe('Archive or unarchive experiment'),
})

export const ExperimentUpdateSchema = z.object({
    experimentId: z.number().describe('The ID of the experiment to update'),
    data: ExperimentUpdateInputSchema.describe(
        'The experiment data to update using user-friendly format'
    ),
})

export const ExperimentCreateSchema = z.object({
    name: z
        .string()
        .min(1)
        .describe('Experiment name - should clearly describe what is being tested'),

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

    type: z
        .enum(['product', 'web'])
        .default('product')
        .describe(
            "Experiment type: 'product' for backend/API changes, 'web' for frontend UI changes"
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
                properties: z.record(z.any()).optional().describe('Event properties to filter on'),
                description: z
                    .string()
                    .optional()
                    .describe(
                        "What this metric measures and why it's important for the experiment"
                    ),
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
                event_name: z
                    .string()
                    .describe("REQUIRED: PostHog event name. Use '$pageview' if unsure."),
                funnel_steps: z
                    .array(z.string())
                    .optional()
                    .describe('For funnel metrics only: Array of event names for each funnel step'),
                properties: z.record(z.any()).optional().describe('Event properties to filter on'),
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
                key: z
                    .string()
                    .describe("Variant key (e.g., 'control', 'variant_a', 'new_design')"),
                name: z.string().optional().describe('Human-readable variant name'),
                rollout_percentage: z
                    .number()
                    .min(0)
                    .max(100)
                    .describe('Percentage of users to show this variant'),
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
    filter_test_accounts: z
        .boolean()
        .default(true)
        .describe('Whether to filter out internal test accounts'),

    target_properties: z
        .record(z.any())
        .optional()
        .describe('Properties to target specific user segments (e.g., country, subscription type)'),

    // Control flags
    draft: z
        .boolean()
        .default(true)
        .describe(
            'Create as draft (true) or launch immediately (false). Recommend draft for review first'
        ),

    holdout_id: z
        .number()
        .optional()
        .describe(
            'Holdout group ID if this experiment should exclude users from other experiments'
        ),
})

export const FeatureFlagCreateSchema = z.object({
    name: z.string(),
    key: z.string(),
    description: z.string(),
    filters: FilterGroupsSchema,
    active: z.boolean(),
    tags: z.array(z.string()).optional(),
})

export const FeatureFlagDeleteSchema = z.object({
    flagKey: z.string(),
})

export const FeatureFlagGetAllSchema = z.object({})

export const FeatureFlagGetDefinitionSchema = z.object({
    flagId: z.number().int().positive().optional(),
    flagKey: z.string().optional(),
})

export const FeatureFlagUpdateSchema = z.object({
    flagKey: z.string(),
    data: UpdateFeatureFlagInputSchema,
})

export const InsightCreateSchema = z.object({
    data: CreateInsightInputSchema,
})

export const InsightDeleteSchema = z.object({
    insightId: z.string(),
})

export const InsightGetSchema = z.object({
    insightId: z.string(),
})

export const InsightGetAllSchema = z.object({
    data: ListInsightsSchema.optional(),
})

export const InsightGenerateHogQLFromQuestionSchema = z.object({
    question: z
        .string()
        .max(1000)
        .describe('Your natural language query describing the SQL insight (max 1000 characters).'),
})

export const InsightQueryInputSchema = z.object({
    insightId: z.string(),
})

export const InsightUpdateSchema = z.object({
    insightId: z.string(),
    data: UpdateInsightInputSchema,
})

export const LLMAnalyticsGetCostsSchema = z.object({
    projectId: z.number().int().positive(),
    days: z.number().optional(),
})

export const OrganizationGetDetailsSchema = z.object({})

export const OrganizationGetAllSchema = z.object({})

export const OrganizationSetActiveSchema = z.object({
    orgId: z.string().uuid(),
})

export const ProjectGetAllSchema = z.object({})

export const ProjectEventDefinitionsSchema = z.object({
    q: z
        .string()
        .optional()
        .describe('Search query to filter event names. Only use if there are lots of events.'),
})

export const ProjectPropertyDefinitionsInputSchema = z.object({
    type: z.enum(['event', 'person']).describe('Type of properties to get'),
    eventName: z
        .string()
        .describe('Event name to filter properties by, required for event type')
        .optional(),
    includePredefinedProperties: z
        .boolean()
        .optional()
        .describe('Whether to include predefined properties'),
})

export const ProjectSetActiveSchema = z.object({
    projectId: z.number().int().positive(),
})

export const SurveyCreateSchema = CreateSurveyInputSchema

export const SurveyResponseCountsSchema = z.object({})

export const SurveyGlobalStatsSchema = GetSurveyStatsInputSchema

export const SurveyStatsSchema = GetSurveySpecificStatsInputSchema

export const SurveyDeleteSchema = z.object({
    surveyId: z.string(),
})

export const SurveyGetSchema = z.object({
    surveyId: z.string(),
})

export const SurveyGetAllSchema = ListSurveysInputSchema

export const SurveyUpdateSchema = UpdateSurveyInputSchema.extend({
    surveyId: z.string(),
})

export const QueryRunInputSchema = z.object({
    query: InsightQuerySchema,
})
