import { z } from 'zod'

import { CreateInsightInputSchema, ListInsightsSchema, UpdateInsightInputSchema } from './insights'
import { InsightQuerySchema } from './query'

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
    experimentId: z.number().describe('The ID of the experiment to get comprehensive results for'),
    refresh: z.boolean().describe('Force refresh of results instead of using cached values'),
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

export const QueryRunInputSchema = z.object({
    query: InsightQuerySchema,
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
