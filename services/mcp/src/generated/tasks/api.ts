/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 11 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * API for managing sandbox environments that control network access for task runs.
 */
export const SandboxListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const sandboxListQueryLimitDefault = 100
export const sandboxListQueryLimitMax = 100

export const sandboxListQueryOffsetDefault = 0
export const sandboxListQueryOffsetMin = 0

export const SandboxListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod
        .number()
        .min(1)
        .max(sandboxListQueryLimitMax)
        .default(sandboxListQueryLimitDefault)
        .describe('Number of results to return per page.'),
    offset: zod
        .number()
        .min(sandboxListQueryOffsetMin)
        .default(sandboxListQueryOffsetDefault)
        .describe('The initial index from which to return the results.'),
})

/**
 * API for managing sandbox environments that control network access for task runs.
 */
export const SandboxRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this sandbox environment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
    created_by: zod.number().optional().describe('Filter by creator user ID'),
    internal: zod
        .boolean()
        .optional()
        .describe('Filter by internal flag. Defaults to excluding internal tasks when not specified.'),
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

export const TasksCreateBody = /* @__PURE__ */ zod.object({
    title: zod
        .string()
        .max(tasksCreateBodyTitleMax)
        .optional()
        .describe('Short human-readable title. Auto-generated from `description` when omitted.'),
    title_manually_set: zod
        .boolean()
        .optional()
        .describe('True when the title was provided by the caller; False when auto-generated from `description`.'),
    description: zod
        .string()
        .optional()
        .describe('Free-form description of the work to be done. Used as the prompt passed to the agent.'),
    origin_product: zod
        .enum([
            'error_tracking',
            'eval_clusters',
            'user_created',
            'automation',
            'slack',
            'support_queue',
            'session_summaries',
            'signal_report',
            'mcp',
        ])
        .describe(
            '* `error_tracking` - Error Tracking\n* `eval_clusters` - Eval Clusters\n* `user_created` - User Created\n* `automation` - Automation\n* `slack` - Slack\n* `support_queue` - Support Queue\n* `session_summaries` - Session Summaries\n* `signal_report` - Signal Report\n* `mcp` - MCP'
        )
        .optional()
        .describe(
            'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created).\n\n* `error_tracking` - Error Tracking\n* `eval_clusters` - Eval Clusters\n* `user_created` - User Created\n* `automation` - Automation\n* `slack` - Slack\n* `support_queue` - Support Queue\n* `session_summaries` - Session Summaries\n* `signal_report` - Signal Report\n* `mcp` - MCP'
        ),
    repository: zod
        .string()
        .max(tasksCreateBodyRepositoryMax)
        .nullish()
        .describe('Target GitHub repository in `organization/repo` format (e.g. `posthog/posthog-js`).'),
    github_integration: zod
        .number()
        .nullish()
        .describe('GitHub integration the agent uses to clone and open pull requests against `repository`.'),
    signal_report: zod.string().nullish(),
    signal_report_task_relationship: zod
        .enum(['implementation'])
        .describe('* `implementation` - Implementation')
        .optional()
        .describe(
            'When linking a task to a signal report, which SignalReportTask relationship row to create. Only `implementation` is supported via the public API.\n\n* `implementation` - Implementation'
        ),
    json_schema: zod
        .unknown()
        .nullish()
        .describe('JSON schema for the task. This is used to validate the output of the task.'),
    internal: zod
        .boolean()
        .optional()
        .describe('If true, this task is for internal use and should not be exposed to end users.'),
    ci_prompt: zod.string().nullish().describe('Custom prompt for CI fixes. If blank, a default prompt will be used.'),
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
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this task.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const tasksPartialUpdateBodyTitleMax = 255

export const tasksPartialUpdateBodyRepositoryMax = 255

export const TasksPartialUpdateBody = /* @__PURE__ */ zod.object({
    title: zod
        .string()
        .max(tasksPartialUpdateBodyTitleMax)
        .optional()
        .describe('Short human-readable title. Auto-generated from `description` when omitted.'),
    title_manually_set: zod
        .boolean()
        .optional()
        .describe('True when the title was provided by the caller; False when auto-generated from `description`.'),
    description: zod
        .string()
        .optional()
        .describe('Free-form description of the work to be done. Used as the prompt passed to the agent.'),
    origin_product: zod
        .enum([
            'error_tracking',
            'eval_clusters',
            'user_created',
            'automation',
            'slack',
            'support_queue',
            'session_summaries',
            'signal_report',
            'mcp',
        ])
        .describe(
            '* `error_tracking` - Error Tracking\n* `eval_clusters` - Eval Clusters\n* `user_created` - User Created\n* `automation` - Automation\n* `slack` - Slack\n* `support_queue` - Support Queue\n* `session_summaries` - Session Summaries\n* `signal_report` - Signal Report\n* `mcp` - MCP'
        )
        .optional()
        .describe(
            'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created).\n\n* `error_tracking` - Error Tracking\n* `eval_clusters` - Eval Clusters\n* `user_created` - User Created\n* `automation` - Automation\n* `slack` - Slack\n* `support_queue` - Support Queue\n* `session_summaries` - Session Summaries\n* `signal_report` - Signal Report\n* `mcp` - MCP'
        ),
    repository: zod
        .string()
        .max(tasksPartialUpdateBodyRepositoryMax)
        .nullish()
        .describe('Target GitHub repository in `organization/repo` format (e.g. `posthog/posthog-js`).'),
    github_integration: zod
        .number()
        .nullish()
        .describe('GitHub integration the agent uses to clone and open pull requests against `repository`.'),
    signal_report: zod.string().nullish(),
    signal_report_task_relationship: zod
        .enum(['implementation'])
        .describe('* `implementation` - Implementation')
        .optional()
        .describe(
            'When linking a task to a signal report, which SignalReportTask relationship row to create. Only `implementation` is supported via the public API.\n\n* `implementation` - Implementation'
        ),
    json_schema: zod
        .unknown()
        .nullish()
        .describe('JSON schema for the task. This is used to validate the output of the task.'),
    internal: zod
        .boolean()
        .optional()
        .describe('If true, this task is for internal use and should not be exposed to end users.'),
    ci_prompt: zod.string().nullish().describe('Custom prompt for CI fixes. If blank, a default prompt will be used.'),
})

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this task.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create a new task run and kick off the workflow.
 * @summary Run task
 */
export const TasksRunCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this task.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const tasksRunCreateBodyOneModeDefault = `background`
export const tasksRunCreateBodyOneBranchMax = 255

export const tasksRunCreateBodyOnePendingUserArtifactIdsItemMax = 128

export const tasksRunCreateBodyTwoModeDefault = `background`
export const tasksRunCreateBodyTwoBranchMax = 255

export const tasksRunCreateBodyTwoPendingUserArtifactIdsItemMax = 128

export const tasksRunCreateBodyThreeModeDefault = `background`
export const tasksRunCreateBodyThreeBranchMax = 255

export const TasksRunCreateBody = /* @__PURE__ */ zod.union([
    zod
        .object({
            mode: zod
                .enum(['interactive', 'background'])
                .describe('* `interactive` - interactive\n* `background` - background')
                .default(tasksRunCreateBodyOneModeDefault)
                .describe(
                    "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n* `interactive` - interactive\n* `background` - background"
                ),
            branch: zod
                .string()
                .max(tasksRunCreateBodyOneBranchMax)
                .nullish()
                .describe('Git branch to checkout in the sandbox'),
            resume_from_run_id: zod
                .string()
                .optional()
                .describe('ID of a previous run to resume from. Must belong to the same task.'),
            pending_user_message: zod
                .string()
                .optional()
                .describe('Initial or follow-up user message to include in the run prompt.'),
            pending_user_artifact_ids: zod
                .array(zod.string().max(tasksRunCreateBodyOnePendingUserArtifactIdsItemMax))
                .optional()
                .describe('Identifiers for staged task artifacts that should be attached to the initial run prompt.'),
            sandbox_environment_id: zod
                .string()
                .optional()
                .describe('Optional sandbox environment to apply for this cloud run.'),
            pr_authorship_mode: zod
                .enum(['user', 'bot'])
                .describe('* `user` - user\n* `bot` - bot')
                .optional()
                .describe(
                    'Whether pull requests for this run should be authored by the user or the bot.\n\n* `user` - user\n* `bot` - bot'
                ),
            run_source: zod
                .enum(['manual', 'signal_report'])
                .describe('* `manual` - manual\n* `signal_report` - signal_report')
                .optional()
                .describe(
                    'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n* `manual` - manual\n* `signal_report` - signal_report'
                ),
            signal_report_id: zod
                .string()
                .optional()
                .describe('Optional signal report identifier when this run was started from Inbox.'),
            runtime_adapter: zod
                .enum(['claude'])
                .describe('* `claude` - claude')
                .describe(
                    "Agent runtime adapter to launch for this run. Must be 'claude' for Claude runtimes.\n\n* `claude` - claude"
                ),
            model: zod.string().describe('LLM model identifier to run in the Claude runtime.'),
            reasoning_effort: zod
                .enum(['low', 'medium', 'high', 'max'])
                .describe('* `low` - low\n* `medium` - medium\n* `high` - high\n* `max` - max')
                .optional()
                .describe(
                    'Reasoning effort to request for models that expose an effort control.\n\n* `low` - low\n* `medium` - medium\n* `high` - high\n* `max` - max'
                ),
            github_user_token: zod
                .string()
                .optional()
                .describe('Ephemeral GitHub user token from PostHog Code for user-authored cloud pull requests.'),
            initial_permission_mode: zod
                .enum(['default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto'])
                .describe(
                    '* `default` - default\n* `acceptEdits` - acceptEdits\n* `plan` - plan\n* `bypassPermissions` - bypassPermissions\n* `auto` - auto'
                )
                .optional()
                .describe(
                    'Initial permission mode for Claude runtimes.\n\n* `default` - default\n* `acceptEdits` - acceptEdits\n* `plan` - plan\n* `bypassPermissions` - bypassPermissions\n* `auto` - auto'
                ),
        })
        .describe('Request body for creating a new task run'),
    zod
        .object({
            mode: zod
                .enum(['interactive', 'background'])
                .describe('* `interactive` - interactive\n* `background` - background')
                .default(tasksRunCreateBodyTwoModeDefault)
                .describe(
                    "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n* `interactive` - interactive\n* `background` - background"
                ),
            branch: zod
                .string()
                .max(tasksRunCreateBodyTwoBranchMax)
                .nullish()
                .describe('Git branch to checkout in the sandbox'),
            resume_from_run_id: zod
                .string()
                .optional()
                .describe('ID of a previous run to resume from. Must belong to the same task.'),
            pending_user_message: zod
                .string()
                .optional()
                .describe('Initial or follow-up user message to include in the run prompt.'),
            pending_user_artifact_ids: zod
                .array(zod.string().max(tasksRunCreateBodyTwoPendingUserArtifactIdsItemMax))
                .optional()
                .describe('Identifiers for staged task artifacts that should be attached to the initial run prompt.'),
            sandbox_environment_id: zod
                .string()
                .optional()
                .describe('Optional sandbox environment to apply for this cloud run.'),
            pr_authorship_mode: zod
                .enum(['user', 'bot'])
                .describe('* `user` - user\n* `bot` - bot')
                .optional()
                .describe(
                    'Whether pull requests for this run should be authored by the user or the bot.\n\n* `user` - user\n* `bot` - bot'
                ),
            run_source: zod
                .enum(['manual', 'signal_report'])
                .describe('* `manual` - manual\n* `signal_report` - signal_report')
                .optional()
                .describe(
                    'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n* `manual` - manual\n* `signal_report` - signal_report'
                ),
            signal_report_id: zod
                .string()
                .optional()
                .describe('Optional signal report identifier when this run was started from Inbox.'),
            runtime_adapter: zod
                .enum(['codex'])
                .describe('* `codex` - codex')
                .describe(
                    "Agent runtime adapter to launch for this run. Must be 'codex' for Codex runtimes.\n\n* `codex` - codex"
                ),
            model: zod.string().describe('LLM model identifier to run in the Codex runtime.'),
            reasoning_effort: zod
                .enum(['low', 'medium', 'high', 'max'])
                .describe('* `low` - low\n* `medium` - medium\n* `high` - high\n* `max` - max')
                .optional()
                .describe(
                    'Reasoning effort to request for models that expose an effort control.\n\n* `low` - low\n* `medium` - medium\n* `high` - high\n* `max` - max'
                ),
            github_user_token: zod
                .string()
                .optional()
                .describe('Ephemeral GitHub user token from PostHog Code for user-authored cloud pull requests.'),
            initial_permission_mode: zod
                .enum(['auto', 'read-only', 'full-access'])
                .describe('* `auto` - auto\n* `read-only` - read-only\n* `full-access` - full-access')
                .optional()
                .describe(
                    'Initial permission mode for Codex runtimes.\n\n* `auto` - auto\n* `read-only` - read-only\n* `full-access` - full-access'
                ),
        })
        .describe('Request body for creating a new task run'),
    zod.object({
        mode: zod
            .enum(['interactive', 'background'])
            .describe('* `interactive` - interactive\n* `background` - background')
            .default(tasksRunCreateBodyThreeModeDefault)
            .describe(
                "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n* `interactive` - interactive\n* `background` - background"
            ),
        branch: zod
            .string()
            .max(tasksRunCreateBodyThreeBranchMax)
            .nullish()
            .describe('Git branch to checkout in the sandbox'),
        resume_from_run_id: zod
            .string()
            .optional()
            .describe('ID of a previous run to resume from. Must belong to the same task.'),
        pending_user_message: zod
            .string()
            .optional()
            .describe('Initial or follow-up user message to include in the run prompt.'),
        sandbox_environment_id: zod
            .string()
            .optional()
            .describe('Optional sandbox environment to apply for this cloud run.'),
        pr_authorship_mode: zod
            .enum(['user', 'bot'])
            .describe('* `user` - user\n* `bot` - bot')
            .optional()
            .describe(
                'Whether pull requests for this run should be authored by the user or the bot.\n\n* `user` - user\n* `bot` - bot'
            ),
        run_source: zod
            .enum(['manual', 'signal_report'])
            .describe('* `manual` - manual\n* `signal_report` - signal_report')
            .optional()
            .describe(
                'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n* `manual` - manual\n* `signal_report` - signal_report'
            ),
        signal_report_id: zod
            .string()
            .optional()
            .describe('Optional signal report identifier when this run was started from Inbox.'),
        github_user_token: zod
            .string()
            .optional()
            .describe('Ephemeral GitHub user token from PostHog Code for user-authored cloud pull requests.'),
    }),
])

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
 * Fetch session log entries for a task run with optional filtering by timestamp, event type, and limit.
 * @summary Get filtered task run session logs
 */
export const TasksRunsSessionLogsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this task run.'),
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
    after: zod.iso.datetime({}).optional().describe('Only return events after this ISO8601 timestamp'),
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
