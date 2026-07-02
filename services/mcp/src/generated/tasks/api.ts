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

export const tasksListQueryLimitDefault = 50
export const tasksListQueryLimitMax = 100

export const tasksListQueryOffsetDefault = 0
export const tasksListQueryOffsetMin = 0

export const TasksListQueryParams = /* @__PURE__ */ zod.object({
    archived: zod
        .enum(['true', 'false', 'all'])
        .optional()
        .describe(
            "Filter by archived state. Defaults to excluding archived tasks. Use 'true' to list only archived tasks, 'false' for the default, or 'all' to include both.\n\n* `true` - true\n* `false` - false\n* `all` - all"
        ),
    created_by: zod.number().optional().describe('Filter by creator user ID'),
    internal: zod
        .enum(['true', 'false', 'all'])
        .optional()
        .describe(
            "Filter by the internal flag, which controls whether a task is shown by default, not whether it is accessible. Defaults to excluding internal tasks. Use 'all' to include both internal and user-facing tasks (available to any team member; access stays governed by task visibility). 'true' lists only internal tasks and is a staff/debug view.\n\n* `true` - true\n* `false` - false\n* `all` - all"
        ),
    limit: zod
        .number()
        .min(1)
        .max(tasksListQueryLimitMax)
        .default(tasksListQueryLimitDefault)
        .describe('Number of results to return per page.'),
    offset: zod
        .number()
        .min(tasksListQueryOffsetMin)
        .default(tasksListQueryOffsetDefault)
        .describe('The initial index from which to return the results.'),
    organization: zod.string().min(1).optional().describe('Filter by repository organization'),
    origin_product: zod.string().min(1).optional().describe('Filter by origin product'),
    repository: zod.string().min(1).optional().describe('Filter by repository name (can include org/repo format)'),
    search: zod
        .string()
        .optional()
        .describe(
            'Case-insensitive substring search over task title and description. A numeric value also matches the task number. An empty value disables the filter.'
        ),
    stage: zod.string().min(1).optional().describe('Filter by task run stage'),
    status: zod
        .enum(['not_started', 'queued', 'in_progress', 'completed', 'failed', 'cancelled'])
        .optional()
        .describe(
            'Filter tasks by the status of their most recent run.\n\n* `not_started` - not_started\n* `queued` - queued\n* `in_progress` - in_progress\n* `completed` - completed\n* `failed` - failed\n* `cancelled` - cancelled'
        ),
})

/**
 * Retrieve a single task by ID.
 * @summary Get task
 */
export const TasksRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
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

export const tasksRunsListQueryLimitDefault = 50
export const tasksRunsListQueryLimitMax = 100

export const tasksRunsListQueryOffsetDefault = 0
export const tasksRunsListQueryOffsetMin = 0

export const TasksRunsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod
        .number()
        .min(1)
        .max(tasksRunsListQueryLimitMax)
        .default(tasksRunsListQueryLimitDefault)
        .describe('Number of results to return per page.'),
    offset: zod
        .number()
        .min(tasksRunsListQueryOffsetMin)
        .default(tasksRunsListQueryOffsetDefault)
        .describe('The initial index from which to return the results.'),
})

/**
 * Retrieve a single run for a specific task.
 * @summary Get task run
 */
export const TasksRunsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    task_id: zod.string(),
})

/**
 * Fetch session log entries for a task run with optional filtering by timestamp, event type, and limit.
 * @summary Get filtered task run session logs
 */
export const TasksRunsSessionLogsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    task_id: zod.string(),
})

export const tasksRunsSessionLogsRetrieveQueryLimitDefault = 1000
export const tasksRunsSessionLogsRetrieveQueryLimitMax = 5000

export const tasksRunsSessionLogsRetrieveQueryOffsetDefault = 0
export const tasksRunsSessionLogsRetrieveQueryOffsetMin = 0

export const TasksRunsSessionLogsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    after: zod.iso.datetime({ offset: true }).optional().describe('Only return events after this ISO8601 timestamp'),
    event_types: zod.string().min(1).optional().describe('Comma-separated list of event types to include'),
    exclude_types: zod.string().min(1).optional().describe('Comma-separated list of event types to exclude'),
    limit: zod
        .number()
        .min(1)
        .max(tasksRunsSessionLogsRetrieveQueryLimitMax)
        .default(tasksRunsSessionLogsRetrieveQueryLimitDefault)
        .describe('Maximum number of entries to return (default 1000, max 5000)'),
    offset: zod
        .number()
        .min(tasksRunsSessionLogsRetrieveQueryOffsetMin)
        .default(tasksRunsSessionLogsRetrieveQueryOffsetDefault)
        .describe('Zero-based offset into the filtered log entries'),
})
