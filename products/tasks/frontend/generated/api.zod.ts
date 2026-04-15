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
export const sandboxListResponseResultsItemNameMax = 255

export const sandboxListResponseResultsItemAllowedDomainsItemMax = 255

export const sandboxListResponseResultsItemRepositoriesItemMax = 255

export const sandboxListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const sandboxListResponseResultsItemCreatedByOneFirstNameMax = 150

export const sandboxListResponseResultsItemCreatedByOneLastNameMax = 150

export const sandboxListResponseResultsItemCreatedByOneEmailMax = 254

export const SandboxListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string().max(sandboxListResponseResultsItemNameMax),
            network_access_level: zod
                .enum(['trusted', 'full', 'custom'])
                .optional()
                .describe('* `trusted` - Trusted\n* `full` - Full\n* `custom` - Custom'),
            allowed_domains: zod
                .array(zod.string().max(sandboxListResponseResultsItemAllowedDomainsItemMax))
                .optional()
                .describe('List of allowed domains for custom network access'),
            repositories: zod
                .array(zod.string().max(sandboxListResponseResultsItemRepositoriesItemMax))
                .optional()
                .describe('List of repositories this environment applies to (format: org/repo)'),
            private: zod
                .boolean()
                .optional()
                .describe('If true, only the creator can see this environment. Otherwise visible to whole team.'),
            internal: zod
                .boolean()
                .optional()
                .describe(
                    'If true, this environment is for internal use (e.g. signals pipeline) and should not be exposed to end users.'
                ),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(sandboxListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(sandboxListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(sandboxListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(sandboxListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
        })
    ),
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

/**
 * Get a list of tasks for the current project, with optional filtering by origin product, stage, organization, repository, and created_by.
 * @summary List tasks
 */
export const TasksListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                title: zod.string(),
                description: zod.string().optional(),
                assignee: zod.string().nullish(),
            })
            .describe('Serializer for extracted tasks')
    ),
})

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksCreateBody = /* @__PURE__ */ zod
    .object({
        title: zod.string(),
        description: zod.string().optional(),
        assignee: zod.string().nullish(),
    })
    .describe('Serializer for extracted tasks')

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksRetrieveResponse = /* @__PURE__ */ zod
    .object({
        title: zod.string(),
        description: zod.string().optional(),
        assignee: zod.string().nullish(),
    })
    .describe('Serializer for extracted tasks')

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksUpdateBody = /* @__PURE__ */ zod
    .object({
        title: zod.string(),
        description: zod.string().optional(),
        assignee: zod.string().nullish(),
    })
    .describe('Serializer for extracted tasks')

export const TasksUpdateResponse = /* @__PURE__ */ zod
    .object({
        title: zod.string(),
        description: zod.string().optional(),
        assignee: zod.string().nullish(),
    })
    .describe('Serializer for extracted tasks')

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
            'slack',
            'support_queue',
            'session_summaries',
            'signal_report',
        ])
        .optional()
        .describe(
            '* `error_tracking` - Error Tracking\n* `eval_clusters` - Eval Clusters\n* `user_created` - User Created\n* `slack` - Slack\n* `support_queue` - Support Queue\n* `session_summaries` - Session Summaries\n* `signal_report` - Signal Report'
        ),
    repository: zod.string().max(tasksPartialUpdateBodyRepositoryMax).nullish(),
    github_integration: zod.number().nullish().describe('GitHub integration for this task'),
    signal_report: zod.uuid().nullish(),
    json_schema: zod
        .unknown()
        .nullish()
        .describe('JSON schema for the task. This is used to validate the output of the task.'),
    internal: zod
        .boolean()
        .optional()
        .describe('If true, this task is for internal use and should not be exposed to end users.'),
})

export const TasksPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        title: zod.string(),
        description: zod.string().optional(),
        assignee: zod.string().nullish(),
    })
    .describe('Serializer for extracted tasks')

/**
 * Create a new task run and kick off the workflow.
 * @summary Run task
 */
export const tasksRunCreateBodyModeDefault = `background`
export const tasksRunCreateBodyBranchMax = 255

export const TasksRunCreateBody = /* @__PURE__ */ zod
    .object({
        mode: zod
            .enum(['interactive', 'background'])
            .describe('* `interactive` - interactive\n* `background` - background')
            .default(tasksRunCreateBodyModeDefault)
            .describe(
                "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n* `interactive` - interactive\n* `background` - background"
            ),
        branch: zod
            .string()
            .max(tasksRunCreateBodyBranchMax)
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
            .describe('Ephemeral GitHub user token from PostHog Code for user-authored cloud pull requests.'),
    })
    .describe('Request body for creating a new task run')

export const TasksRunCreateResponse = /* @__PURE__ */ zod
    .object({
        title: zod.string(),
        description: zod.string().optional(),
        assignee: zod.string().nullish(),
    })
    .describe('Serializer for extracted tasks')

/**
 * Get a list of runs for a specific task.
 * @summary List task runs
 */
export const tasksRunsListResponseResultsItemStageMax = 100

export const tasksRunsListResponseResultsItemBranchMax = 255

export const TasksRunsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            task: zod.uuid(),
            stage: zod
                .string()
                .max(tasksRunsListResponseResultsItemStageMax)
                .nullish()
                .describe("Current stage for this run (e.g., 'research', 'plan', 'build')"),
            branch: zod
                .string()
                .max(tasksRunsListResponseResultsItemBranchMax)
                .nullish()
                .describe('Branch name for the run'),
            status: zod
                .enum(['not_started', 'queued', 'in_progress', 'completed', 'failed', 'cancelled'])
                .optional()
                .describe(
                    '* `not_started` - Not Started\n* `queued` - Queued\n* `in_progress` - In Progress\n* `completed` - Completed\n* `failed` - Failed\n* `cancelled` - Cancelled'
                ),
            environment: zod
                .enum(['local', 'cloud'])
                .describe('* `local` - Local\n* `cloud` - Cloud')
                .optional()
                .describe('Execution environment\n\n* `local` - Local\n* `cloud` - Cloud'),
            log_url: zod.url().nullable().describe('Presigned S3 URL for log access (valid for 1 hour).'),
            error_message: zod.string().nullish().describe('Error message if execution failed'),
            output: zod.unknown().nullish().describe('Run output data (e.g., PR URL, commit SHA, etc.)'),
            state: zod.unknown().optional().describe('Run state data for resuming or tracking execution state'),
            artifacts: zod.array(
                zod.object({
                    name: zod.string().describe('Artifact file name'),
                    type: zod.string().describe('Artifact classification (plan, context, etc.)'),
                    size: zod.number().optional().describe('Artifact size in bytes'),
                    content_type: zod.string().optional().describe('Optional MIME type'),
                    storage_path: zod.string().describe('S3 object key for the artifact'),
                    uploaded_at: zod.string().describe('Timestamp when the artifact was uploaded'),
                })
            ),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
            completed_at: zod.iso.datetime({}).nullable(),
        })
    ),
})

/**
 * API for managing task runs. Each run represents an execution of a task.
 */
export const tasksRunsRetrieveResponseStageMax = 100

export const tasksRunsRetrieveResponseBranchMax = 255

export const TasksRunsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    task: zod.uuid(),
    stage: zod
        .string()
        .max(tasksRunsRetrieveResponseStageMax)
        .nullish()
        .describe("Current stage for this run (e.g., 'research', 'plan', 'build')"),
    branch: zod.string().max(tasksRunsRetrieveResponseBranchMax).nullish().describe('Branch name for the run'),
    status: zod
        .enum(['not_started', 'queued', 'in_progress', 'completed', 'failed', 'cancelled'])
        .optional()
        .describe(
            '* `not_started` - Not Started\n* `queued` - Queued\n* `in_progress` - In Progress\n* `completed` - Completed\n* `failed` - Failed\n* `cancelled` - Cancelled'
        ),
    environment: zod
        .enum(['local', 'cloud'])
        .describe('* `local` - Local\n* `cloud` - Cloud')
        .optional()
        .describe('Execution environment\n\n* `local` - Local\n* `cloud` - Cloud'),
    log_url: zod.url().nullable().describe('Presigned S3 URL for log access (valid for 1 hour).'),
    error_message: zod.string().nullish().describe('Error message if execution failed'),
    output: zod.unknown().nullish().describe('Run output data (e.g., PR URL, commit SHA, etc.)'),
    state: zod.unknown().optional().describe('Run state data for resuming or tracking execution state'),
    artifacts: zod.array(
        zod.object({
            name: zod.string().describe('Artifact file name'),
            type: zod.string().describe('Artifact classification (plan, context, etc.)'),
            size: zod.number().optional().describe('Artifact size in bytes'),
            content_type: zod.string().optional().describe('Optional MIME type'),
            storage_path: zod.string().describe('S3 object key for the artifact'),
            uploaded_at: zod.string().describe('Timestamp when the artifact was uploaded'),
        })
    ),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    completed_at: zod.iso.datetime({}).nullable(),
})

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
    error_message: zod.string().nullish().describe('Error message if execution failed'),
})

export const tasksRunsPartialUpdateResponseStageMax = 100

export const tasksRunsPartialUpdateResponseBranchMax = 255

export const TasksRunsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    task: zod.uuid(),
    stage: zod
        .string()
        .max(tasksRunsPartialUpdateResponseStageMax)
        .nullish()
        .describe("Current stage for this run (e.g., 'research', 'plan', 'build')"),
    branch: zod.string().max(tasksRunsPartialUpdateResponseBranchMax).nullish().describe('Branch name for the run'),
    status: zod
        .enum(['not_started', 'queued', 'in_progress', 'completed', 'failed', 'cancelled'])
        .optional()
        .describe(
            '* `not_started` - Not Started\n* `queued` - Queued\n* `in_progress` - In Progress\n* `completed` - Completed\n* `failed` - Failed\n* `cancelled` - Cancelled'
        ),
    environment: zod
        .enum(['local', 'cloud'])
        .describe('* `local` - Local\n* `cloud` - Cloud')
        .optional()
        .describe('Execution environment\n\n* `local` - Local\n* `cloud` - Cloud'),
    log_url: zod.url().nullable().describe('Presigned S3 URL for log access (valid for 1 hour).'),
    error_message: zod.string().nullish().describe('Error message if execution failed'),
    output: zod.unknown().nullish().describe('Run output data (e.g., PR URL, commit SHA, etc.)'),
    state: zod.unknown().optional().describe('Run state data for resuming or tracking execution state'),
    artifacts: zod.array(
        zod.object({
            name: zod.string().describe('Artifact file name'),
            type: zod.string().describe('Artifact classification (plan, context, etc.)'),
            size: zod.number().optional().describe('Artifact size in bytes'),
            content_type: zod.string().optional().describe('Optional MIME type'),
            storage_path: zod.string().describe('S3 object key for the artifact'),
            uploaded_at: zod.string().describe('Timestamp when the artifact was uploaded'),
        })
    ),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    completed_at: zod.iso.datetime({}).nullable(),
})

/**
 * Append one or more log entries to the task run log array
 * @summary Append log entries
 */
export const TasksRunsAppendLogCreateBody = /* @__PURE__ */ zod.object({
    entries: zod.array(zod.record(zod.string(), zod.unknown())).describe('Array of log entry dictionaries to append'),
})

export const tasksRunsAppendLogCreateResponseStageMax = 100

export const tasksRunsAppendLogCreateResponseBranchMax = 255

export const TasksRunsAppendLogCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    task: zod.uuid(),
    stage: zod
        .string()
        .max(tasksRunsAppendLogCreateResponseStageMax)
        .nullish()
        .describe("Current stage for this run (e.g., 'research', 'plan', 'build')"),
    branch: zod.string().max(tasksRunsAppendLogCreateResponseBranchMax).nullish().describe('Branch name for the run'),
    status: zod
        .enum(['not_started', 'queued', 'in_progress', 'completed', 'failed', 'cancelled'])
        .optional()
        .describe(
            '* `not_started` - Not Started\n* `queued` - Queued\n* `in_progress` - In Progress\n* `completed` - Completed\n* `failed` - Failed\n* `cancelled` - Cancelled'
        ),
    environment: zod
        .enum(['local', 'cloud'])
        .describe('* `local` - Local\n* `cloud` - Cloud')
        .optional()
        .describe('Execution environment\n\n* `local` - Local\n* `cloud` - Cloud'),
    log_url: zod.url().nullable().describe('Presigned S3 URL for log access (valid for 1 hour).'),
    error_message: zod.string().nullish().describe('Error message if execution failed'),
    output: zod.unknown().nullish().describe('Run output data (e.g., PR URL, commit SHA, etc.)'),
    state: zod.unknown().optional().describe('Run state data for resuming or tracking execution state'),
    artifacts: zod.array(
        zod.object({
            name: zod.string().describe('Artifact file name'),
            type: zod.string().describe('Artifact classification (plan, context, etc.)'),
            size: zod.number().optional().describe('Artifact size in bytes'),
            content_type: zod.string().optional().describe('Optional MIME type'),
            storage_path: zod.string().describe('S3 object key for the artifact'),
            uploaded_at: zod.string().describe('Timestamp when the artifact was uploaded'),
        })
    ),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    completed_at: zod.iso.datetime({}).nullable(),
})

/**
 * Persist task artifacts to S3 and attach them to the run manifest.
 * @summary Upload artifacts for a task run
 */
export const tasksRunsArtifactsCreateBodyArtifactsItemNameMax = 255

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
                    .enum(['plan', 'context', 'reference', 'output', 'artifact', 'tree_snapshot'])
                    .describe(
                        '* `plan` - plan\n* `context` - context\n* `reference` - reference\n* `output` - output\n* `artifact` - artifact\n* `tree_snapshot` - tree_snapshot'
                    )
                    .describe(
                        'Classification for the artifact\n\n* `plan` - plan\n* `context` - context\n* `reference` - reference\n* `output` - output\n* `artifact` - artifact\n* `tree_snapshot` - tree_snapshot'
                    ),
                content: zod.string().describe('Raw file contents (UTF-8 string or base64 data)'),
                content_type: zod
                    .string()
                    .max(tasksRunsArtifactsCreateBodyArtifactsItemContentTypeMax)
                    .optional()
                    .describe('Optional MIME type for the artifact'),
            })
        )
        .describe('Array of artifacts to upload'),
})

export const TasksRunsArtifactsCreateResponse = /* @__PURE__ */ zod.object({
    artifacts: zod
        .array(
            zod.object({
                name: zod.string().describe('Artifact file name'),
                type: zod.string().describe('Artifact classification (plan, context, etc.)'),
                size: zod.number().optional().describe('Artifact size in bytes'),
                content_type: zod.string().optional().describe('Optional MIME type'),
                storage_path: zod.string().describe('S3 object key for the artifact'),
                uploaded_at: zod.string().describe('Timestamp when the artifact was uploaded'),
            })
        )
        .describe('Updated list of artifacts on the run'),
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

export const TasksRunsArtifactsPresignCreateResponse = /* @__PURE__ */ zod.object({
    url: zod.url().describe('Presigned URL for downloading the artifact'),
    expires_in: zod.number().describe('URL expiry in seconds'),
})

/**
 * Forward a JSON-RPC command to the agent server running in the sandbox. Supports user_message, cancel, and close commands.
 * @summary Send command to agent server
 */
export const TasksRunsCommandCreateBody = /* @__PURE__ */ zod
    .object({
        jsonrpc: zod
            .enum(['2.0'])
            .describe('* `2.0` - 2.0')
            .describe("JSON-RPC version, must be '2.0'\n\n* `2.0` - 2.0"),
        method: zod
            .enum(['user_message', 'cancel', 'close'])
            .describe('* `user_message` - user_message\n* `cancel` - cancel\n* `close` - close')
            .describe(
                'Command method to execute on the agent server\n\n* `user_message` - user_message\n* `cancel` - cancel\n* `close` - close'
            ),
        params: zod.record(zod.string(), zod.unknown()).optional().describe('Parameters for the command'),
        id: zod.unknown().optional().describe('Optional JSON-RPC request ID (string or number)'),
    })
    .describe('JSON-RPC request to send a command to the agent server in the sandbox.')

export const TasksRunsCommandCreateResponse = /* @__PURE__ */ zod
    .object({
        jsonrpc: zod.string().describe('JSON-RPC version'),
        id: zod.unknown().optional().describe('Request ID echoed back (string or number)'),
        result: zod.record(zod.string(), zod.unknown()).optional().describe('Command result on success'),
        error: zod.record(zod.string(), zod.unknown()).optional().describe('Error details on failure'),
    })
    .describe('Response from the agent server command endpoint.')

/**
 * Generate a JWT token for direct connection to the sandbox. Valid for 24 hours.
 * @summary Get sandbox connection token
 */
export const TasksRunsConnectionTokenRetrieveResponse = /* @__PURE__ */ zod
    .object({
        token: zod.string().describe('JWT token for authenticating with the sandbox'),
    })
    .describe('Response containing a JWT token for direct sandbox connection')

/**
 * Queue a Slack relay workflow to post a run message into the mapped Slack thread.
 * @summary Relay run message to Slack
 */
export const tasksRunsRelayMessageCreateBodyTextMax = 10000

export const TasksRunsRelayMessageCreateBody = /* @__PURE__ */ zod.object({
    text: zod.string().max(tasksRunsRelayMessageCreateBodyTextMax),
})

export const TasksRunsRelayMessageCreateResponse = /* @__PURE__ */ zod.object({
    status: zod.string().describe("Relay status: 'accepted' or 'skipped'"),
    relay_id: zod.string().optional().describe('Relay workflow ID when accepted'),
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

export const tasksRunsSetOutputPartialUpdateResponseStageMax = 100

export const tasksRunsSetOutputPartialUpdateResponseBranchMax = 255

export const TasksRunsSetOutputPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    task: zod.uuid(),
    stage: zod
        .string()
        .max(tasksRunsSetOutputPartialUpdateResponseStageMax)
        .nullish()
        .describe("Current stage for this run (e.g., 'research', 'plan', 'build')"),
    branch: zod
        .string()
        .max(tasksRunsSetOutputPartialUpdateResponseBranchMax)
        .nullish()
        .describe('Branch name for the run'),
    status: zod
        .enum(['not_started', 'queued', 'in_progress', 'completed', 'failed', 'cancelled'])
        .optional()
        .describe(
            '* `not_started` - Not Started\n* `queued` - Queued\n* `in_progress` - In Progress\n* `completed` - Completed\n* `failed` - Failed\n* `cancelled` - Cancelled'
        ),
    environment: zod
        .enum(['local', 'cloud'])
        .describe('* `local` - Local\n* `cloud` - Cloud')
        .optional()
        .describe('Execution environment\n\n* `local` - Local\n* `cloud` - Cloud'),
    log_url: zod.url().nullable().describe('Presigned S3 URL for log access (valid for 1 hour).'),
    error_message: zod.string().nullish().describe('Error message if execution failed'),
    output: zod.unknown().nullish().describe('Run output data (e.g., PR URL, commit SHA, etc.)'),
    state: zod.unknown().optional().describe('Run state data for resuming or tracking execution state'),
    artifacts: zod.array(
        zod.object({
            name: zod.string().describe('Artifact file name'),
            type: zod.string().describe('Artifact classification (plan, context, etc.)'),
            size: zod.number().optional().describe('Artifact size in bytes'),
            content_type: zod.string().optional().describe('Optional MIME type'),
            storage_path: zod.string().describe('S3 object key for the artifact'),
            uploaded_at: zod.string().describe('Timestamp when the artifact was uploaded'),
        })
    ),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    completed_at: zod.iso.datetime({}).nullable(),
})

/**
 * Get autonomy readiness details for a specific repository in the current project.
 * @summary Get repository readiness
 */
export const TasksRepositoryReadinessRetrieveResponse = /* @__PURE__ */ zod.object({
    repository: zod.string().describe('Normalized repository identifier'),
    classification: zod.string().describe('Repository classification'),
    excluded: zod.boolean().describe('Whether the repository is excluded from readiness checks'),
    coreSuggestions: zod
        .object({
            state: zod
                .enum(['needs_setup', 'detected', 'waiting_for_data', 'ready', 'not_applicable', 'unknown'])
                .describe(
                    '* `needs_setup` - needs_setup\n* `detected` - detected\n* `waiting_for_data` - waiting_for_data\n* `ready` - ready\n* `not_applicable` - not_applicable\n* `unknown` - unknown'
                )
                .describe(
                    'Current state of the capability\n\n* `needs_setup` - needs_setup\n* `detected` - detected\n* `waiting_for_data` - waiting_for_data\n* `ready` - ready\n* `not_applicable` - not_applicable\n* `unknown` - unknown'
                ),
            estimated: zod.boolean().describe('Whether the state is estimated from static analysis'),
            reason: zod.string().describe('Human-readable explanation'),
            evidence: zod.record(zod.string(), zod.unknown()).optional().describe('Supporting evidence'),
        })
        .describe('Tracking capability state'),
    replayInsights: zod
        .object({
            state: zod
                .enum(['needs_setup', 'detected', 'waiting_for_data', 'ready', 'not_applicable', 'unknown'])
                .describe(
                    '* `needs_setup` - needs_setup\n* `detected` - detected\n* `waiting_for_data` - waiting_for_data\n* `ready` - ready\n* `not_applicable` - not_applicable\n* `unknown` - unknown'
                )
                .describe(
                    'Current state of the capability\n\n* `needs_setup` - needs_setup\n* `detected` - detected\n* `waiting_for_data` - waiting_for_data\n* `ready` - ready\n* `not_applicable` - not_applicable\n* `unknown` - unknown'
                ),
            estimated: zod.boolean().describe('Whether the state is estimated from static analysis'),
            reason: zod.string().describe('Human-readable explanation'),
            evidence: zod.record(zod.string(), zod.unknown()).optional().describe('Supporting evidence'),
        })
        .describe('Computer vision capability state'),
    errorInsights: zod
        .object({
            state: zod
                .enum(['needs_setup', 'detected', 'waiting_for_data', 'ready', 'not_applicable', 'unknown'])
                .describe(
                    '* `needs_setup` - needs_setup\n* `detected` - detected\n* `waiting_for_data` - waiting_for_data\n* `ready` - ready\n* `not_applicable` - not_applicable\n* `unknown` - unknown'
                )
                .describe(
                    'Current state of the capability\n\n* `needs_setup` - needs_setup\n* `detected` - detected\n* `waiting_for_data` - waiting_for_data\n* `ready` - ready\n* `not_applicable` - not_applicable\n* `unknown` - unknown'
                ),
            estimated: zod.boolean().describe('Whether the state is estimated from static analysis'),
            reason: zod.string().describe('Human-readable explanation'),
            evidence: zod.record(zod.string(), zod.unknown()).optional().describe('Supporting evidence'),
        })
        .describe('Error tracking capability state'),
    overall: zod.string().describe('Overall readiness state'),
    evidenceTaskCount: zod.number().describe('Count of replay-derived evidence tasks'),
    windowDays: zod.number().describe('Lookback window in days'),
    generatedAt: zod.string().describe('ISO timestamp when the response was generated'),
    cacheAgeSeconds: zod.number().describe('Age of cached response in seconds'),
    scan: zod
        .object({
            filesScanned: zod.number().describe('Number of files scanned'),
            detectedFilesCount: zod.number().describe('Total candidate files detected'),
            eventNameCount: zod.number().describe('Number of distinct event names found'),
            foundPosthogInit: zod.boolean().describe('Whether posthog.init() was found in scanned files'),
            foundPosthogCapture: zod.boolean().describe('Whether posthog.capture() was found in scanned files'),
            foundErrorSignal: zod.boolean().describe('Whether error tracking signals were found in scanned files'),
        })
        .optional()
        .describe('Scan evidence details'),
})
