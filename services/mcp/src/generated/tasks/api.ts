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

export const tasksListQueryAllTeamTasksDefault = false
export const tasksListQueryLimitDefault = 50
export const tasksListQueryLimitMax = 100

export const tasksListQueryOffsetDefault = 0
export const tasksListQueryOffsetMin = 0

export const TasksListQueryParams = /* @__PURE__ */ zod.object({
    all_team_tasks: zod
        .boolean()
        .default(tasksListQueryAllTeamTasksDefault)
        .describe(
            'Staff-only. When true, list every task on the team regardless of creator or channel, bypassing the per-user visibility filter. Ignored for non-staff users.'
        ),
    archived: zod
        .enum(['true', 'false', 'all'])
        .optional()
        .describe(
            "Filter by archived state. Defaults to excluding archived tasks. Use 'true' to list only archived tasks, 'false' for the default, or 'all' to include both.\n\n* `true` - true\n* `false` - false\n* `all` - all"
        ),
    channel: zod.string().optional().describe("Filter tasks to a channel's feed."),
    created_by: zod.number().optional().describe('Filter by creator user ID'),
    internal: zod
        .enum(['true', 'false', 'all'])
        .optional()
        .describe(
            "Filter by the internal flag, which controls whether a task is shown by default, not whether it is accessible. Defaults to excluding internal tasks. Use 'all' to include both internal and user-facing tasks, or 'true' to list only internal tasks. All values are available to any team member; access stays governed by task visibility.\n\n* `true` - true\n* `false` - false\n* `all` - all"
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

export const tasksCreateBodySignalReportTaskRelationshipMax = 200

export const tasksCreateBodyBranchMax = 255

export const tasksCreateBodyPendingUserArtifactIdsItemMax = 128

export const TasksCreateBody = /* @__PURE__ */ zod
    .object({
        title: zod
            .string()
            .max(tasksCreateBodyTitleMax)
            .optional()
            .describe('Short human-readable title. Auto-generated from `description` when omitted.'),
        title_manually_set: zod
            .boolean()
            .optional()
            .describe('Whether the title was set by a human (vs auto-generated from the description).'),
        description: zod
            .string()
            .optional()
            .describe('Free-form description of the work to be done. Used as the prompt passed to the agent.'),
        origin_product: zod
            .enum([
                'onboarding',
                'error_tracking',
                'eval_clusters',
                'user_created',
                'automation',
                'slack',
                'support_queue',
                'session_summaries',
                'posthog_ai',
                'experiments',
                'signal_report',
                'signals_scout',
                'support_reply',
                'hogdesk',
                'review_hog',
                'image_builder',
            ])
            .describe(
                '* `onboarding` - Onboarding\n* `error_tracking` - Error Tracking\n* `eval_clusters` - Eval Clusters\n* `user_created` - User Created\n* `automation` - Automation\n* `slack` - Slack\n* `support_queue` - Support Queue\n* `session_summaries` - Session Summaries\n* `posthog_ai` - PostHog AI\n* `experiments` - Experiments\n* `signal_report` - Signal Report\n* `signals_scout` - Signals Scout\n* `support_reply` - Support Reply\n* `hogdesk` - HogDesk\n* `review_hog` - ReviewHog\n* `image_builder` - Image Builder'
            )
            .optional()
            .describe(
                'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created).\n\n* `onboarding` - Onboarding\n* `error_tracking` - Error Tracking\n* `eval_clusters` - Eval Clusters\n* `user_created` - User Created\n* `automation` - Automation\n* `slack` - Slack\n* `support_queue` - Support Queue\n* `session_summaries` - Session Summaries\n* `posthog_ai` - PostHog AI\n* `experiments` - Experiments\n* `signal_report` - Signal Report\n* `signals_scout` - Signals Scout\n* `support_reply` - Support Reply\n* `hogdesk` - HogDesk\n* `review_hog` - ReviewHog\n* `image_builder` - Image Builder'
            ),
        repository: zod
            .string()
            .max(tasksCreateBodyRepositoryMax)
            .nullish()
            .describe('Target GitHub repository in `organization/repo` format (e.g. `posthog/posthog-js`).'),
        github_integration: zod.number().nullish().describe('GitHub integration for this task.'),
        github_user_integration: zod
            .string()
            .nullish()
            .describe('User-scoped GitHub integration to use for user-authored cloud runs.'),
        signal_report: zod
            .string()
            .nullish()
            .describe('Signal report this task implements, when created from a report.'),
        signal_report_task_relationship: zod
            .string()
            .max(tasksCreateBodySignalReportTaskRelationshipMax)
            .optional()
            .describe(
                "How the created task relates to the signal report (e.g. 'implementation', 'discussion', 'research'). Recorded as a signals task_run work-log entry; 'implementation' also opens the auto-start spend gate. Any routing-safe identifier (lowercase letters, numbers, '_', '-') is accepted."
            ),
        json_schema: zod.unknown().optional().describe('JSON schema used to validate the output of the task.'),
        internal: zod
            .boolean()
            .optional()
            .describe('If true, this task is for internal use and should not be exposed to end users.'),
        archived: zod.boolean().optional().describe('If true, the task is hidden from default list responses.'),
        ci_prompt: zod
            .string()
            .nullish()
            .describe('Custom prompt for CI fixes. If blank, a default prompt will be used.'),
        branch: zod
            .string()
            .max(tasksCreateBodyBranchMax)
            .nullish()
            .describe(
                'Branch the user has selected for this cloud task. Write-only and not persisted on the task itself: used only to reuse a matching pre-warmed sandbox Run on creation (the branch is otherwise carried on the run). Omit to match a warm Run on the default branch.'
            ),
        runtime_adapter: zod
            .union([zod.enum(['claude', 'codex']).describe('* `claude` - claude\n* `codex` - codex'), zod.null()])
            .optional()
            .describe(
                "Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: used only to reuse a pre-warmed Run started on the same runtime. A value differing from the warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime.\n\n* `claude` - claude\n* `codex` - codex"
            ),
        model: zod
            .string()
            .nullish()
            .describe(
                'Selected LLM model identifier. Write-only; used only to reuse a warm Run started on the same model.'
            ),
        reasoning_effort: zod
            .union([
                zod
                    .enum(['low', 'medium', 'high', 'xhigh', 'max'])
                    .describe('* `low` - low\n* `medium` - medium\n* `high` - high\n* `xhigh` - xhigh\n* `max` - max'),
                zod.null(),
            ])
            .optional()
            .describe(
                'Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.\n\n* `low` - low\n* `medium` - medium\n* `high` - high\n* `xhigh` - xhigh\n* `max` - max'
            ),
        pending_user_message: zod
            .string()
            .nullish()
            .describe(
                'First user message to forward when creation reuses a pre-warmed Run. Write-only and not persisted on the task: lets clients deliver a message that differs from `description` (e.g. a resolved skill invocation with channel context folded in). Ignored when no warm Run is reused — cold creation takes the first message via the run start endpoint instead.'
            ),
        pending_user_artifact_ids: zod
            .array(zod.string().max(tasksCreateBodyPendingUserArtifactIdsItemMax))
            .optional()
            .describe(
                "Run artifact ids (already uploaded to the pre-warmed Run) to attach to the forwarded first message when creation reuses that warm Run, e.g. skill bundles or file attachments. If any id is missing from the warm Run's manifest, warm reuse is skipped and the task is created cold. Ignored when no warm Run is matched."
            ),
        auto_publish: zod
            .boolean()
            .nullish()
            .describe(
                "When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask. Write-only and not persisted on the task: persisted into the reused warm Run's state when creation activates one, so resumes of that Run honor it. Ignored when no warm Run is reused — cold creation takes it via the run start endpoint instead."
            ),
        channel: zod.string().nullish().describe('Channel this task is owned by (the channel it was kicked off in).'),
        runtime: zod
            .enum(['acp', 'pi'])
            .describe('* `acp` - ACP\n* `pi` - Pi')
            .optional()
            .describe(
                "Agent protocol and harness used for this task's runs. Defaults to ACP when omitted.\n\n* `acp` - ACP\n* `pi` - Pi"
            ),
    })
    .describe(
        'Request body for creating or updating a task.\n\nField required/default semantics match the ``Task`` model. The view passes\n``validated_data`` (integration/report PK fields already resolved to instances) to the\nfacade ``create_task`` / ``update_task`` functions.'
    )

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
