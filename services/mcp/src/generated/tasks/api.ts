/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Get a list of tasks for the current project, with optional filtering by origin product, stage, organization, repository, and created_by.
 * @summary List tasks
 */
export const TasksListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const TasksListQueryParams = /* @__PURE__ */ zod.object({
    created_by: zod.number().optional().describe('Filter by creator user ID'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    organization: zod.string().min(1).optional().describe('Filter by repository organization'),
    origin_product: zod.string().min(1).optional().describe('Filter by origin product'),
    repository: zod.string().min(1).optional().describe('Filter by repository name (can include org/repo format)'),
    stage: zod.string().min(1).optional().describe('Filter by task run stage'),
})

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const tasksCreateBodyTitleMax = 255

export const tasksCreateBodyRepositoryMax = 255

export const TasksCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(tasksCreateBodyTitleMax).optional(),
    title_manually_set: zod.boolean().optional(),
    description: zod.string().optional(),
    origin_product: zod
        .enum([
            'error_tracking',
            'eval_clusters',
            'user_created',
            'slack',
            'support_queue',
            'session_summaries',
            'hogbot',
        ])
        .optional()
        .describe(
            '* `error_tracking` - Error Tracking\n* `eval_clusters` - Eval Clusters\n* `user_created` - User Created\n* `slack` - Slack\n* `support_queue` - Support Queue\n* `session_summaries` - Session Summaries\n* `hogbot` - Hogbot'
        ),
    repository: zod.string().max(tasksCreateBodyRepositoryMax).nullish(),
    github_integration: zod.number().nullish().describe('GitHub integration for this task'),
    json_schema: zod
        .unknown()
        .nullish()
        .describe('JSON schema for the task. This is used to validate the output of the task.'),
})

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this task.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Get a list of runs for a specific task.
 * @summary List task runs
 */
export const TasksRunsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    task_id: zod.string(),
})

export const TasksRunsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * API for managing task runs. Each run represents an execution of a task.
 */
export const TasksRunsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this task run.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    task_id: zod.string(),
})

/**
 * Get autonomy readiness details for a specific repository in the current project.
 * @summary Get repository readiness
 */
export const TasksRepositoryReadinessRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const tasksRepositoryReadinessRetrieveQueryRefreshDefault = false
export const tasksRepositoryReadinessRetrieveQueryWindowDaysDefault = 7
export const tasksRepositoryReadinessRetrieveQueryWindowDaysMax = 30

export const TasksRepositoryReadinessRetrieveQueryParams = /* @__PURE__ */ zod.object({
    refresh: zod.boolean().default(tasksRepositoryReadinessRetrieveQueryRefreshDefault),
    repository: zod.string().min(1).describe('Repository in org/repo format'),
    window_days: zod
        .number()
        .min(1)
        .max(tasksRepositoryReadinessRetrieveQueryWindowDaysMax)
        .default(tasksRepositoryReadinessRetrieveQueryWindowDaysDefault),
})
