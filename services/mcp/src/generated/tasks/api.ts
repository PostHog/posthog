/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 10 enabled ops
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
        .boolean()
        .optional()
        .describe(
            'When true, list internal tasks instead of user-facing ones. Honored in debug environments or for staff users; ignored for non-staff users in production. Defaults to excluding internal tasks.'
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
 * Returns stable, versioned artifact handles created by a task run.
 * @summary List living artifacts for a task run
 */
export const TasksRunsLivingArtifactsListParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    task_id: zod.string(),
})

/**
 * Create a stable, editable artifact handle from direct markdown/text content or an existing run artifact. Slack adapters deliver into the mapped Slack thread; document artifacts use connector storage when available and S3 fallback otherwise.
 * @summary Create a living artifact for a task run
 */
export const TasksRunsLivingArtifactsCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    task_id: zod.string(),
})

export const tasksRunsLivingArtifactsCreateBodyNameMax = 255

export const tasksRunsLivingArtifactsCreateBodyArtifactTypeDefault = `document`
export const tasksRunsLivingArtifactsCreateBodyContentMax = 500000

export const tasksRunsLivingArtifactsCreateBodyContentTypeMax = 255

export const tasksRunsLivingArtifactsCreateBodySlackChannelIdMax = 80

export const tasksRunsLivingArtifactsCreateBodySlackThreadTsMax = 80

export const TasksRunsLivingArtifactsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(tasksRunsLivingArtifactsCreateBodyNameMax)
        .describe('Human-readable artifact name, used as the title.'),
    artifact_type: zod
        .enum(['slack_message', 'slack_canvas', 'document', 'spreadsheet', 'dashboard', 'file', 'github_pr'])
        .describe(
            '* `slack_message` - slack_message\n* `slack_canvas` - slack_canvas\n* `document` - document\n* `spreadsheet` - spreadsheet\n* `dashboard` - dashboard\n* `file` - file\n* `github_pr` - github_pr'
        )
        .default(tasksRunsLivingArtifactsCreateBodyArtifactTypeDefault)
        .describe(
            'Artifact format or delivery surface to create, such as document, spreadsheet, slack_canvas, or file.\n\n* `slack_message` - slack_message\n* `slack_canvas` - slack_canvas\n* `document` - document\n* `spreadsheet` - spreadsheet\n* `dashboard` - dashboard\n* `file` - file\n* `github_pr` - github_pr'
        ),
    adapter: zod
        .enum(['slack_message', 'slack_canvas', 'slack_file', 'document_connector', 's3', 'github_pr'])
        .describe(
            '* `slack_message` - slack_message\n* `slack_canvas` - slack_canvas\n* `slack_file` - slack_file\n* `document_connector` - document_connector\n* `s3` - s3\n* `github_pr` - github_pr'
        )
        .optional()
        .describe(
            'Optional preferred storage or delivery adapter. Slack adapters deliver into the mapped Slack thread; omitted document and spreadsheet artifacts use connector storage with S3 fallback.\n\n* `slack_message` - slack_message\n* `slack_canvas` - slack_canvas\n* `slack_file` - slack_file\n* `document_connector` - document_connector\n* `s3` - s3\n* `github_pr` - github_pr'
        ),
    content: zod
        .string()
        .max(tasksRunsLivingArtifactsCreateBodyContentMax)
        .optional()
        .describe('Markdown or text content for the initial artifact version.'),
    content_base64: zod
        .string()
        .optional()
        .describe(
            'Base64-encoded binary content for Slack file uploads or binary S3-backed artifacts. Prefer source_artifact_id or source_storage_path for large files that were already uploaded as run artifacts.'
        ),
    content_type: zod
        .string()
        .max(tasksRunsLivingArtifactsCreateBodyContentTypeMax)
        .optional()
        .describe(
            'MIME type for content_base64 or source-backed artifacts, such as application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.'
        ),
    source_artifact_id: zod
        .string()
        .optional()
        .describe('Existing run artifact id to use as the initial content source.'),
    source_storage_path: zod
        .string()
        .optional()
        .describe('Existing run artifact storage_path to use as the initial content source.'),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Optional metadata to persist with the living artifact.'),
    slack_delivery_mode: zod
        .enum(['send', 'draft'])
        .describe('* `send` - send\n* `draft` - draft')
        .optional()
        .describe(
            "For slack_message artifacts, use 'draft' to post a Slack approval card before sending or 'send' to preserve immediate delivery into the mapped Slack thread.\n\n* `send` - send\n* `draft` - draft"
        ),
    slack_channel_id: zod
        .string()
        .max(tasksRunsLivingArtifactsCreateBodySlackChannelIdMax)
        .optional()
        .describe(
            "For slack_message drafts, optional target Slack channel ID such as C123. Defaults to the run's mapped Slack channel."
        ),
    slack_thread_ts: zod
        .string()
        .max(tasksRunsLivingArtifactsCreateBodySlackThreadTsMax)
        .optional()
        .describe(
            'For slack_message drafts, optional target Slack thread timestamp. Omit to post in the target channel root.'
        ),
})

/**
 * Return a stable living artifact handle and the current content when the adapter supports reads.
 * @summary Open a living artifact for a task run
 */
export const TasksRunsLivingArtifactsOpenParams = /* @__PURE__ */ zod.object({
    artifact_id: zod.string(),
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    task_id: zod.string(),
})

/**
 * Commit a new version to an existing living artifact handle.
 * @summary Edit a living artifact for a task run
 */
export const TasksRunsLivingArtifactsEditParams = /* @__PURE__ */ zod.object({
    artifact_id: zod.string(),
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    task_id: zod.string(),
})

export const tasksRunsLivingArtifactsEditBodyNameMax = 255

export const tasksRunsLivingArtifactsEditBodyContentMax = 500000

export const tasksRunsLivingArtifactsEditBodyContentTypeMax = 255

export const tasksRunsLivingArtifactsEditBodySlackChannelIdMax = 80

export const tasksRunsLivingArtifactsEditBodySlackThreadTsMax = 80

export const TasksRunsLivingArtifactsEditBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(tasksRunsLivingArtifactsEditBodyNameMax)
        .optional()
        .describe('Optional new human-readable artifact name.'),
    content: zod
        .string()
        .max(tasksRunsLivingArtifactsEditBodyContentMax)
        .optional()
        .describe('Markdown or text content for the next version.'),
    content_base64: zod
        .string()
        .optional()
        .describe('Base64-encoded binary content for the next version, used by adapters such as slack_file.'),
    content_type: zod
        .string()
        .max(tasksRunsLivingArtifactsEditBodyContentTypeMax)
        .optional()
        .describe('MIME type for content_base64 or source-backed edits.'),
    source_artifact_id: zod
        .string()
        .optional()
        .describe('Existing run artifact id to use as the next version content source.'),
    source_storage_path: zod
        .string()
        .optional()
        .describe('Existing run artifact storage_path to use as the next version content source.'),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Optional metadata to merge into the artifact registry record.'),
    slack_delivery_mode: zod
        .enum(['send', 'draft'])
        .describe('* `send` - send\n* `draft` - draft')
        .optional()
        .describe(
            'For unsent slack_message drafts, keep or switch the artifact to draft mode before approval.\n\n* `send` - send\n* `draft` - draft'
        ),
    slack_channel_id: zod
        .string()
        .max(tasksRunsLivingArtifactsEditBodySlackChannelIdMax)
        .optional()
        .describe('For unsent slack_message drafts, optional replacement target Slack channel ID such as C123.'),
    slack_thread_ts: zod
        .string()
        .max(tasksRunsLivingArtifactsEditBodySlackThreadTsMax)
        .optional()
        .describe('For unsent slack_message drafts, optional replacement target Slack thread timestamp.'),
})

/**
 * Send an unsent slack_message living artifact that was created with slack_delivery_mode='draft'. Use only after the user has explicitly approved the draft.
 * @summary Send a drafted Slack message artifact
 */
export const TasksRunsLivingArtifactsSendParams = /* @__PURE__ */ zod.object({
    artifact_id: zod.string(),
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
