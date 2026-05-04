/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Redeem a PostHog Code invite code to enable access.
 * @summary Redeem invite code
 */
export const codeInvitesRedeemCreateBodyCodeMax = 50

export const CodeInvitesRedeemCreateBody = /* @__PURE__ */ zod.object({
    code: zod.string().max(codeInvitesRedeemCreateBodyCodeMax),
})

/**
 * API for managing sandbox environments that control network access for task runs.
 */
export const sandboxCreateBodyNameMax = 255

export const sandboxCreateBodyAllowedDomainsItemMax = 255

export const sandboxCreateBodyRepositoriesItemMax = 255

export const SandboxCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(sandboxCreateBodyNameMax),
    network_access_level: zod
        .enum(['trusted', 'full', 'custom'])
        .optional()
        .describe('* `trusted` - Trusted\n* `full` - Full\n* `custom` - Custom'),
    allowed_domains: zod
        .array(zod.string().max(sandboxCreateBodyAllowedDomainsItemMax))
        .optional()
        .describe('List of allowed domains for custom network access'),
    include_default_domains: zod
        .boolean()
        .optional()
        .describe('Whether to include default trusted domains (GitHub, npm, PyPI)'),
    repositories: zod
        .array(zod.string().max(sandboxCreateBodyRepositoriesItemMax))
        .optional()
        .describe('List of repositories this environment applies to (format: org/repo)'),
    environment_variables: zod
        .unknown()
        .optional()
        .describe('Encrypted environment variables (write-only, never returned in responses)'),
    private: zod
        .boolean()
        .optional()
        .describe('If true, only the creator can see this environment. Otherwise visible to whole team.'),
})

export const taskAutomationsCreateBodyNameMax = 255

export const taskAutomationsCreateBodyRepositoryMax = 255

export const taskAutomationsCreateBodyCronExpressionMax = 100

export const taskAutomationsCreateBodyTimezoneMax = 128

export const taskAutomationsCreateBodyTemplateIdMax = 255

export const TaskAutomationsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(taskAutomationsCreateBodyNameMax),
    prompt: zod.string(),
    repository: zod.string().max(taskAutomationsCreateBodyRepositoryMax),
    github_integration: zod.number().nullish(),
    cron_expression: zod.string().max(taskAutomationsCreateBodyCronExpressionMax),
    timezone: zod.string().max(taskAutomationsCreateBodyTimezoneMax).optional(),
    template_id: zod.string().max(taskAutomationsCreateBodyTemplateIdMax).nullish(),
    enabled: zod.boolean().optional(),
})

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
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
            'automation',
            'slack',
            'support_queue',
            'session_summaries',
            'signal_report',
        ])
        .optional()
        .describe(
            '* `error_tracking` - Error Tracking\n* `eval_clusters` - Eval Clusters\n* `user_created` - User Created\n* `automation` - Automation\n* `slack` - Slack\n* `support_queue` - Support Queue\n* `session_summaries` - Session Summaries\n* `signal_report` - Signal Report'
        ),
    repository: zod.string().max(tasksCreateBodyRepositoryMax).nullish(),
    github_integration: zod.number().nullish().describe('GitHub integration for this task'),
    github_user_integration: zod
        .uuid()
        .nullish()
        .describe('User-scoped GitHub integration to use for user-authored cloud runs.'),
    signal_report: zod.uuid().nullish(),
    signal_report_task_relationship: zod
        .enum(['implementation'])
        .describe('* `implementation` - Implementation')
        .optional(),
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
export const tasksUpdateBodyTitleMax = 255

export const tasksUpdateBodyRepositoryMax = 255

export const TasksUpdateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(tasksUpdateBodyTitleMax).optional(),
    title_manually_set: zod.boolean().optional(),
    description: zod.string().optional(),
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
        ])
        .optional()
        .describe(
            '* `error_tracking` - Error Tracking\n* `eval_clusters` - Eval Clusters\n* `user_created` - User Created\n* `automation` - Automation\n* `slack` - Slack\n* `support_queue` - Support Queue\n* `session_summaries` - Session Summaries\n* `signal_report` - Signal Report'
        ),
    repository: zod.string().max(tasksUpdateBodyRepositoryMax).nullish(),
    github_integration: zod.number().nullish().describe('GitHub integration for this task'),
    github_user_integration: zod
        .uuid()
        .nullish()
        .describe('User-scoped GitHub integration to use for user-authored cloud runs.'),
    signal_report: zod.uuid().nullish(),
    signal_report_task_relationship: zod
        .enum(['implementation'])
        .describe('* `implementation` - Implementation')
        .optional(),
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
export const tasksPartialUpdateBodyTitleMax = 255

export const tasksPartialUpdateBodyRepositoryMax = 255

export const TasksPartialUpdateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(tasksPartialUpdateBodyTitleMax).optional(),
    title_manually_set: zod.boolean().optional(),
    description: zod.string().optional(),
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
        ])
        .optional()
        .describe(
            '* `error_tracking` - Error Tracking\n* `eval_clusters` - Eval Clusters\n* `user_created` - User Created\n* `automation` - Automation\n* `slack` - Slack\n* `support_queue` - Support Queue\n* `session_summaries` - Session Summaries\n* `signal_report` - Signal Report'
        ),
    repository: zod.string().max(tasksPartialUpdateBodyRepositoryMax).nullish(),
    github_integration: zod.number().nullish().describe('GitHub integration for this task'),
    github_user_integration: zod
        .uuid()
        .nullish()
        .describe('User-scoped GitHub integration to use for user-authored cloud runs.'),
    signal_report: zod.uuid().nullish(),
    signal_report_task_relationship: zod
        .enum(['implementation'])
        .describe('* `implementation` - Implementation')
        .optional(),
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
 * Create a new task run and kick off the workflow.
 * @summary Run task
 */
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
                .uuid()
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
                .uuid()
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
                .enum(['low', 'medium', 'high', 'xhigh', 'max'])
                .describe('* `low` - low\n* `medium` - medium\n* `high` - high\n* `xhigh` - xhigh\n* `max` - max')
                .optional()
                .describe(
                    'Reasoning effort to request for models that expose an effort control.\n\n* `low` - low\n* `medium` - medium\n* `high` - high\n* `xhigh` - xhigh\n* `max` - max'
                ),
            github_user_token: zod
                .string()
                .optional()
                .describe(
                    'Optional GitHub user token from PostHog Code for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens.'
                ),
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
                .uuid()
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
                .uuid()
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
                .enum(['low', 'medium', 'high', 'xhigh', 'max'])
                .describe('* `low` - low\n* `medium` - medium\n* `high` - high\n* `xhigh` - xhigh\n* `max` - max')
                .optional()
                .describe(
                    'Reasoning effort to request for models that expose an effort control.\n\n* `low` - low\n* `medium` - medium\n* `high` - high\n* `xhigh` - xhigh\n* `max` - max'
                ),
            github_user_token: zod
                .string()
                .optional()
                .describe(
                    'Optional GitHub user token from PostHog Code for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens.'
                ),
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
            .uuid()
            .optional()
            .describe('ID of a previous run to resume from. Must belong to the same task.'),
        pending_user_message: zod
            .string()
            .optional()
            .describe('Initial or follow-up user message to include in the run prompt.'),
        sandbox_environment_id: zod
            .uuid()
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
            .describe(
                'Optional GitHub user token from PostHog Code for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens.'
            ),
    }),
])

/**
 * Verify staged S3 uploads and cache their metadata so they can be attached to the next run created for this task.
 * @summary Finalize staged direct uploads for task attachments
 */
export const tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemNameMax = 255

export const tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemSourceDefault = ``
export const tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemSourceMax = 64

export const tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemStoragePathMax = 500

export const tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemContentTypeMax = 255

export const TasksStagedArtifactsFinalizeUploadCreateBody = /* @__PURE__ */ zod.object({
    artifacts: zod
        .array(
            zod.object({
                id: zod.string().describe('Stable identifier returned by the staged prepare upload endpoint'),
                name: zod
                    .string()
                    .max(tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemNameMax)
                    .describe('File name associated with the staged artifact'),
                type: zod
                    .enum(['plan', 'context', 'reference', 'output', 'artifact', 'tree_snapshot', 'user_attachment'])
                    .describe(
                        '* `plan` - plan\n* `context` - context\n* `reference` - reference\n* `output` - output\n* `artifact` - artifact\n* `tree_snapshot` - tree_snapshot\n* `user_attachment` - user_attachment'
                    )
                    .describe(
                        'Classification for the artifact\n\n* `plan` - plan\n* `context` - context\n* `reference` - reference\n* `output` - output\n* `artifact` - artifact\n* `tree_snapshot` - tree_snapshot\n* `user_attachment` - user_attachment'
                    ),
                source: zod
                    .string()
                    .max(tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemSourceMax)
                    .default(tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemSourceDefault)
                    .describe('Optional source label for the artifact, such as agent_output or user_attachment'),
                storage_path: zod
                    .string()
                    .max(tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemStoragePathMax)
                    .describe('S3 object key returned by the prepare step'),
                content_type: zod
                    .string()
                    .max(tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemContentTypeMax)
                    .optional()
                    .describe('Optional MIME type recorded for the artifact'),
            })
        )
        .describe('Array of staged artifacts to finalize after upload'),
})

/**
 * Reserve S3 object keys for task attachments before creating a new run and return presigned POST forms for direct uploads.
 * @summary Prepare staged direct uploads for task attachments
 */
export const tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemNameMax = 255

export const tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemSourceDefault = ``
export const tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemSourceMax = 64

export const tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemSizeMax = 31457280

export const tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemContentTypeMax = 255

export const TasksStagedArtifactsPrepareUploadCreateBody = /* @__PURE__ */ zod.object({
    artifacts: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .max(tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemNameMax)
                    .describe('File name to associate with the staged artifact'),
                type: zod
                    .enum(['plan', 'context', 'reference', 'output', 'artifact', 'tree_snapshot', 'user_attachment'])
                    .describe(
                        '* `plan` - plan\n* `context` - context\n* `reference` - reference\n* `output` - output\n* `artifact` - artifact\n* `tree_snapshot` - tree_snapshot\n* `user_attachment` - user_attachment'
                    )
                    .describe(
                        'Classification for the artifact\n\n* `plan` - plan\n* `context` - context\n* `reference` - reference\n* `output` - output\n* `artifact` - artifact\n* `tree_snapshot` - tree_snapshot\n* `user_attachment` - user_attachment'
                    ),
                source: zod
                    .string()
                    .max(tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemSourceMax)
                    .default(tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemSourceDefault)
                    .describe('Optional source label for the artifact, such as agent_output or user_attachment'),
                size: zod
                    .number()
                    .min(1)
                    .max(tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemSizeMax)
                    .describe('Expected upload size in bytes (max 31457280 bytes)'),
                content_type: zod
                    .string()
                    .max(tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemContentTypeMax)
                    .optional()
                    .describe('Optional MIME type for the artifact upload'),
            })
        )
        .describe('Array of staged artifacts to prepare before creating a run'),
})

/**
 * Create a new run for a specific task without starting execution.
 * @summary Create task run
 */
export const tasksRunsCreateBodyEnvironmentDefault = `local`
export const tasksRunsCreateBodyModeDefault = `background`
export const tasksRunsCreateBodyBranchMax = 255

export const TasksRunsCreateBody = /* @__PURE__ */ zod
    .object({
        environment: zod
            .enum(['local', 'cloud'])
            .describe('* `local` - local\n* `cloud` - cloud')
            .default(tasksRunsCreateBodyEnvironmentDefault)
            .describe(
                "Execution environment for the new run. Use 'cloud' for remote sandbox runs and 'local' for desktop sessions.\n\n* `local` - local\n* `cloud` - cloud"
            ),
        mode: zod
            .enum(['interactive', 'background'])
            .describe('* `interactive` - interactive\n* `background` - background')
            .default(tasksRunsCreateBodyModeDefault)
            .describe(
                "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n* `interactive` - interactive\n* `background` - background"
            ),
        branch: zod
            .string()
            .max(tasksRunsCreateBodyBranchMax)
            .nullish()
            .describe('Git branch to checkout in the sandbox'),
        sandbox_environment_id: zod
            .uuid()
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
            .enum(['claude', 'codex'])
            .describe('* `claude` - claude\n* `codex` - codex')
            .optional()
            .describe(
                "Agent runtime adapter to launch for this run. Use 'claude' for the Claude runtime or 'codex' for the Codex runtime.\n\n* `claude` - claude\n* `codex` - codex"
            ),
        model: zod.string().optional().describe('LLM model identifier to run in the selected runtime.'),
        reasoning_effort: zod
            .enum(['low', 'medium', 'high', 'xhigh', 'max'])
            .describe('* `low` - low\n* `medium` - medium\n* `high` - high\n* `xhigh` - xhigh\n* `max` - max')
            .optional()
            .describe(
                'Reasoning effort to request for models that expose an effort control.\n\n* `low` - low\n* `medium` - medium\n* `high` - high\n* `xhigh` - xhigh\n* `max` - max'
            ),
        github_user_token: zod
            .string()
            .optional()
            .describe('Ephemeral GitHub user token from PostHog Code for user-authored cloud pull requests.'),
        initial_permission_mode: zod
            .enum(['default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto', 'read-only', 'full-access'])
            .describe(
                '* `default` - default\n* `acceptEdits` - acceptEdits\n* `plan` - plan\n* `bypassPermissions` - bypassPermissions\n* `auto` - auto\n* `read-only` - read-only\n* `full-access` - full-access'
            )
            .optional()
            .describe(
                "Initial permission mode for the agent session. Claude runtimes accept PostHog permission presets like 'plan'. Codex runtimes accept native Codex modes like 'auto' and 'read-only'.\n\n* `default` - default\n* `acceptEdits` - acceptEdits\n* `plan` - plan\n* `bypassPermissions` - bypassPermissions\n* `auto` - auto\n* `read-only` - read-only\n* `full-access` - full-access"
            ),
    })
    .describe('Request body for creating a task run without starting execution yet.')

/**
 * API for managing task runs. Each run represents an execution of a task.
 * @summary Update task run
 */
export const TasksRunsPartialUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['not_started', 'queued', 'in_progress', 'completed', 'failed', 'cancelled'])
        .describe(
            '* `not_started` - not_started\n* `queued` - queued\n* `in_progress` - in_progress\n* `completed` - completed\n* `failed` - failed\n* `cancelled` - cancelled'
        )
        .optional()
        .describe(
            'Current execution status\n\n* `not_started` - not_started\n* `queued` - queued\n* `in_progress` - in_progress\n* `completed` - completed\n* `failed` - failed\n* `cancelled` - cancelled'
        ),
    branch: zod.string().nullish().describe('Git branch name to associate with the task'),
    stage: zod.string().nullish().describe('Current stage of the run (e.g. research, plan, build)'),
    output: zod.unknown().nullish().describe('Output from the run'),
    state: zod.unknown().optional().describe('State of the run'),
    state_remove_keys: zod
        .array(zod.string())
        .optional()
        .describe('State keys to remove atomically before applying any state updates.'),
    error_message: zod.string().nullish().describe('Error message if execution failed'),
    environment: zod
        .enum(['local'])
        .describe('* `local` - local')
        .optional()
        .describe(
            'Transition a cloud run to local. Use the resume_in_cloud action to move a run into cloud.\n\n* `local` - local'
        ),
})

/**
 * Append one or more log entries to the task run log array
 * @summary Append log entries
 */
export const TasksRunsAppendLogCreateBody = /* @__PURE__ */ zod.object({
    entries: zod.array(zod.record(zod.string(), zod.unknown())).describe('Array of log entry dictionaries to append'),
})

/**
 * Persist task artifacts to S3 and attach them to the run manifest.
 * @summary Upload artifacts for a task run
 */
export const tasksRunsArtifactsCreateBodyArtifactsItemNameMax = 255

export const tasksRunsArtifactsCreateBodyArtifactsItemSourceDefault = ``
export const tasksRunsArtifactsCreateBodyArtifactsItemSourceMax = 64

export const tasksRunsArtifactsCreateBodyArtifactsItemContentEncodingDefault = `utf-8`
export const tasksRunsArtifactsCreateBodyArtifactsItemContentTypeMax = 255

export const TasksRunsArtifactsCreateBody = /* @__PURE__ */ zod.object({
    artifacts: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .max(tasksRunsArtifactsCreateBodyArtifactsItemNameMax)
                    .describe('File name to associate with the artifact'),
                type: zod
                    .enum(['plan', 'context', 'reference', 'output', 'artifact', 'tree_snapshot', 'user_attachment'])
                    .describe(
                        '* `plan` - plan\n* `context` - context\n* `reference` - reference\n* `output` - output\n* `artifact` - artifact\n* `tree_snapshot` - tree_snapshot\n* `user_attachment` - user_attachment'
                    )
                    .describe(
                        'Classification for the artifact\n\n* `plan` - plan\n* `context` - context\n* `reference` - reference\n* `output` - output\n* `artifact` - artifact\n* `tree_snapshot` - tree_snapshot\n* `user_attachment` - user_attachment'
                    ),
                source: zod
                    .string()
                    .max(tasksRunsArtifactsCreateBodyArtifactsItemSourceMax)
                    .default(tasksRunsArtifactsCreateBodyArtifactsItemSourceDefault)
                    .describe('Optional source label for the artifact, such as agent_output or user_attachment'),
                content: zod.string().describe('Artifact contents encoded according to content_encoding'),
                content_encoding: zod
                    .enum(['utf-8', 'base64'])
                    .describe('* `utf-8` - utf-8\n* `base64` - base64')
                    .default(tasksRunsArtifactsCreateBodyArtifactsItemContentEncodingDefault)
                    .describe(
                        'Encoding used for content. Use base64 for binary files and utf-8 for text payloads.\n\n* `utf-8` - utf-8\n* `base64` - base64'
                    ),
                content_type: zod
                    .string()
                    .max(tasksRunsArtifactsCreateBodyArtifactsItemContentTypeMax)
                    .optional()
                    .describe('Optional MIME type for the artifact'),
            })
        )
        .describe('Array of artifacts to upload'),
})

/**
 * Streams artifact content for a task run artifact after validating that it belongs to the run.
 * @summary Download an artifact through the backend
 */
export const tasksRunsArtifactsDownloadCreateBodyStoragePathMax = 500

export const TasksRunsArtifactsDownloadCreateBody = /* @__PURE__ */ zod.object({
    storage_path: zod
        .string()
        .max(tasksRunsArtifactsDownloadCreateBodyStoragePathMax)
        .describe('S3 storage path returned in the artifact manifest'),
})

/**
 * Verify directly uploaded S3 objects and attach them to the run artifact manifest.
 * @summary Finalize direct uploads for task run artifacts
 */
export const tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemNameMax = 255

export const tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemSourceDefault = ``
export const tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemSourceMax = 64

export const tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemStoragePathMax = 500

export const tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemContentTypeMax = 255

export const TasksRunsArtifactsFinalizeUploadCreateBody = /* @__PURE__ */ zod.object({
    artifacts: zod
        .array(
            zod.object({
                id: zod.string().describe('Stable identifier returned by the prepare upload endpoint'),
                name: zod
                    .string()
                    .max(tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemNameMax)
                    .describe('File name associated with the artifact'),
                type: zod
                    .enum(['plan', 'context', 'reference', 'output', 'artifact', 'tree_snapshot', 'user_attachment'])
                    .describe(
                        '* `plan` - plan\n* `context` - context\n* `reference` - reference\n* `output` - output\n* `artifact` - artifact\n* `tree_snapshot` - tree_snapshot\n* `user_attachment` - user_attachment'
                    )
                    .describe(
                        'Classification for the artifact\n\n* `plan` - plan\n* `context` - context\n* `reference` - reference\n* `output` - output\n* `artifact` - artifact\n* `tree_snapshot` - tree_snapshot\n* `user_attachment` - user_attachment'
                    ),
                source: zod
                    .string()
                    .max(tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemSourceMax)
                    .default(tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemSourceDefault)
                    .describe('Optional source label for the artifact, such as agent_output or user_attachment'),
                storage_path: zod
                    .string()
                    .max(tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemStoragePathMax)
                    .describe('S3 object key returned by the prepare step'),
                content_type: zod
                    .string()
                    .max(tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemContentTypeMax)
                    .optional()
                    .describe('Optional MIME type recorded for the artifact'),
            })
        )
        .describe('Array of uploaded artifacts to finalize'),
})

/**
 * Reserve S3 object keys for task artifacts and return presigned POST forms for direct uploads.
 * @summary Prepare direct uploads for task run artifacts
 */
export const tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemNameMax = 255

export const tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemSourceDefault = ``
export const tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemSourceMax = 64

export const tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemSizeMax = 31457280

export const tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemContentTypeMax = 255

export const TasksRunsArtifactsPrepareUploadCreateBody = /* @__PURE__ */ zod.object({
    artifacts: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .max(tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemNameMax)
                    .describe('File name to associate with the artifact'),
                type: zod
                    .enum(['plan', 'context', 'reference', 'output', 'artifact', 'tree_snapshot', 'user_attachment'])
                    .describe(
                        '* `plan` - plan\n* `context` - context\n* `reference` - reference\n* `output` - output\n* `artifact` - artifact\n* `tree_snapshot` - tree_snapshot\n* `user_attachment` - user_attachment'
                    )
                    .describe(
                        'Classification for the artifact\n\n* `plan` - plan\n* `context` - context\n* `reference` - reference\n* `output` - output\n* `artifact` - artifact\n* `tree_snapshot` - tree_snapshot\n* `user_attachment` - user_attachment'
                    ),
                source: zod
                    .string()
                    .max(tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemSourceMax)
                    .default(tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemSourceDefault)
                    .describe('Optional source label for the artifact, such as agent_output or user_attachment'),
                size: zod
                    .number()
                    .min(1)
                    .max(tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemSizeMax)
                    .describe('Expected upload size in bytes (max 31457280 bytes)'),
                content_type: zod
                    .string()
                    .max(tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemContentTypeMax)
                    .optional()
                    .describe('Optional MIME type for the artifact upload'),
            })
        )
        .describe('Array of artifacts to prepare'),
})

/**
 * Returns a temporary, signed URL that can be used to download a specific artifact.
 * @summary Generate presigned URL for an artifact
 */
export const tasksRunsArtifactsPresignCreateBodyStoragePathMax = 500

export const TasksRunsArtifactsPresignCreateBody = /* @__PURE__ */ zod.object({
    storage_path: zod
        .string()
        .max(tasksRunsArtifactsPresignCreateBodyStoragePathMax)
        .describe('S3 storage path returned in the artifact manifest'),
})

/**
 * Forward a JSON-RPC command to the agent server running in the sandbox. Supports user_message, cancel, close, permission_response, and set_config_option commands.
 * @summary Send command to agent server
 */
export const TasksRunsCommandCreateBody = /* @__PURE__ */ zod
    .object({
        jsonrpc: zod
            .enum(['2.0'])
            .describe('* `2.0` - 2.0')
            .describe("JSON-RPC version, must be '2.0'\n\n* `2.0` - 2.0"),
        method: zod
            .enum(['user_message', 'cancel', 'close', 'permission_response', 'set_config_option'])
            .describe(
                '* `user_message` - user_message\n* `cancel` - cancel\n* `close` - close\n* `permission_response` - permission_response\n* `set_config_option` - set_config_option'
            )
            .describe(
                'Command method to execute on the agent server\n\n* `user_message` - user_message\n* `cancel` - cancel\n* `close` - close\n* `permission_response` - permission_response\n* `set_config_option` - set_config_option'
            ),
        params: zod.record(zod.string(), zod.unknown()).optional().describe('Parameters for the command'),
        id: zod.unknown().optional().describe('Optional JSON-RPC request ID (string or number)'),
    })
    .describe('JSON-RPC request to send a command to the agent server in the sandbox.')

/**
 * Queue a Slack relay workflow to post a run message into the mapped Slack thread.
 * @summary Relay run message to Slack
 */
export const tasksRunsRelayMessageCreateBodyTextMax = 10000

export const TasksRunsRelayMessageCreateBody = /* @__PURE__ */ zod.object({
    text: zod.string().max(tasksRunsRelayMessageCreateBodyTextMax),
})

/**
 * Update the output field for a task run (e.g., PR URL, commit SHA, etc.)
 * @summary Set run output
 */
export const TasksRunsSetOutputPartialUpdateBody = /* @__PURE__ */ zod.object({
    output: zod
        .unknown()
        .optional()
        .describe("Output data from the run. Validated against the task's json_schema if one is set."),
})

/**
 * Start an existing cloud run after any initial run-scoped attachments have been uploaded.
 * @summary Start task run
 */
export const tasksRunsStartCreateBodyPendingUserArtifactIdsItemMax = 128

export const TasksRunsStartCreateBody = /* @__PURE__ */ zod.object({
    pending_user_message: zod
        .string()
        .optional()
        .describe('Initial or follow-up user message to include in the run prompt.'),
    pending_user_artifact_ids: zod
        .array(zod.string().max(tasksRunsStartCreateBodyPendingUserArtifactIdsItemMax))
        .optional()
        .describe(
            'Identifiers for run artifacts that should be attached to the next user message delivered to the sandbox.'
        ),
})
