/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const LlmAnalyticsClusteringJobsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsClusteringJobsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const LlmAnalyticsClusteringJobsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this clustering job.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * 
Generate an AI-powered summary of evaluation results.

This endpoint analyzes evaluation runs and identifies patterns in passing
and failing evaluations, providing actionable recommendations.

Data is fetched server-side by evaluation ID to ensure data integrity.

**Use Cases:**
- Understand why evaluations are passing or failing
- Identify systematic issues in LLM responses
- Get recommendations for improving response quality
- Review patterns across many evaluation runs at once
        
 */
export const LlmAnalyticsEvaluationSummaryCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmAnalyticsEvaluationSummaryCreateBodyFilterDefault = `all`
export const llmAnalyticsEvaluationSummaryCreateBodyGenerationIdsMax = 250

export const llmAnalyticsEvaluationSummaryCreateBodyForceRefreshDefault = false

export const LlmAnalyticsEvaluationSummaryCreateBody = /* @__PURE__ */ zod
    .object({
        evaluation_id: zod.string().describe('UUID of the evaluation config to summarize'),
        filter: zod
            .enum(['all', 'pass', 'fail', 'na'])
            .describe('* `all` - all\n* `pass` - pass\n* `fail` - fail\n* `na` - na')
            .default(llmAnalyticsEvaluationSummaryCreateBodyFilterDefault)
            .describe(
                "Filter type to apply ('all', 'pass', 'fail', or 'na')\n\n* `all` - all\n* `pass` - pass\n* `fail` - fail\n* `na` - na"
            ),
        generation_ids: zod
            .array(zod.string())
            .max(llmAnalyticsEvaluationSummaryCreateBodyGenerationIdsMax)
            .optional()
            .describe('Optional: specific generation IDs to include in summary (max 250)'),
        force_refresh: zod
            .boolean()
            .default(llmAnalyticsEvaluationSummaryCreateBodyForceRefreshDefault)
            .describe('If true, bypass cache and generate a fresh summary'),
    })
    .describe('Request serializer for evaluation summary - accepts IDs only, fetches data server-side.')

export const LlmAnalyticsSentimentCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmAnalyticsSentimentCreateBodyIdsMax = 5

export const llmAnalyticsSentimentCreateBodyAnalysisLevelDefault = `trace`
export const llmAnalyticsSentimentCreateBodyForceRefreshDefault = false

export const LlmAnalyticsSentimentCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.string())
        .min(1)
        .max(llmAnalyticsSentimentCreateBodyIdsMax)
        .describe('Trace IDs or generation IDs to classify, depending on analysis_level.'),
    analysis_level: zod
        .enum(['trace', 'generation'])
        .describe('* `trace` - trace\n* `generation` - generation')
        .default(llmAnalyticsSentimentCreateBodyAnalysisLevelDefault)
        .describe(
            "Whether the IDs are 'trace' IDs or 'generation' IDs.\n\n* `trace` - trace\n* `generation` - generation"
        ),
    force_refresh: zod
        .boolean()
        .default(llmAnalyticsSentimentCreateBodyForceRefreshDefault)
        .describe('If true, bypass cache and reclassify.'),
    date_from: zod
        .string()
        .nullish()
        .describe("Start of date range for the lookup (e.g. '-7d' or '2026-01-01'). Defaults to -30d."),
    date_to: zod.string().nullish().describe('End of date range for the lookup. Defaults to now.'),
})

/**
 * 
Generate an AI-powered summary of an LLM trace or event.

This endpoint analyzes the provided trace/event, generates a line-numbered text
representation, and uses an LLM to create a concise summary with line references.

**Two ways to use this endpoint:**

1. **By ID (recommended):** Pass `trace_id` or `generation_id` with an optional `date_from`/`date_to`.
   The backend fetches the data automatically. `summarize_type` is inferred.
2. **By data:** Pass the full trace/event data blob in `data` with `summarize_type`.
   This is how the frontend uses it.

**Summary Format:**
- Title (concise, max 10 words)
- Mermaid flow diagram showing the main flow
- 3-10 summary bullets with line references
- "Interesting Notes" section for failures, successes, or unusual patterns
- Line references in [L45] or [L45-52] format pointing to relevant sections

The response includes the structured summary, the text representation, and metadata.
        
 */
export const LlmAnalyticsSummarizationCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmAnalyticsSummarizationCreateBodyModeDefault = `minimal`
export const llmAnalyticsSummarizationCreateBodyForceRefreshDefault = false

export const LlmAnalyticsSummarizationCreateBody = /* @__PURE__ */ zod.object({
    summarize_type: zod
        .enum(['trace', 'event'])
        .describe('* `trace` - trace\n* `event` - event')
        .optional()
        .describe(
            'Type of entity to summarize. Inferred automatically when using trace_id or generation_id.\n\n* `trace` - trace\n* `event` - event'
        ),
    mode: zod
        .enum(['minimal', 'detailed'])
        .describe('* `minimal` - minimal\n* `detailed` - detailed')
        .default(llmAnalyticsSummarizationCreateBodyModeDefault)
        .describe(
            "Summary detail level: 'minimal' for 3-5 points, 'detailed' for 5-10 points\n\n* `minimal` - minimal\n* `detailed` - detailed"
        ),
    data: zod
        .unknown()
        .optional()
        .describe(
            'Data to summarize. For traces: {trace, hierarchy}. For events: {event}. Not required when using trace_id or generation_id.'
        ),
    force_refresh: zod
        .boolean()
        .default(llmAnalyticsSummarizationCreateBodyForceRefreshDefault)
        .describe('Force regenerate summary, bypassing cache'),
    model: zod.string().nullish().describe('LLM model to use (defaults based on provider)'),
    trace_id: zod
        .string()
        .optional()
        .describe(
            'Trace ID to summarize. The backend fetches the trace data automatically. Requires date_from for efficient lookup.'
        ),
    generation_id: zod
        .string()
        .optional()
        .describe(
            'Generation event UUID to summarize. The backend fetches the event data automatically. Requires date_from for efficient lookup.'
        ),
    date_from: zod
        .string()
        .nullish()
        .describe("Start of date range for ID-based lookup (e.g. '-7d' or '2026-01-01'). Defaults to -30d."),
    date_to: zod.string().nullish().describe('End of date range for ID-based lookup. Defaults to now.'),
})
