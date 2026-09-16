/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 17 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List channels the requester can access, sorted by name and ID. Includes public channels, their personal #me channel, and private channels they belong to. Call provision_defaults to create missing default channels. Send limit and offset to get a page with count, next, previous, and results. Without limit, the response is an array of all accessible channels.
 * @summary List channels
 */
export const TaskChannelsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const TaskChannelsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Create a channel. Public channels use lowercase names with hyphens. If a public channel has that name, return it. The name general returns the project's general space. Private channels always get a new ID, even if another channel has the same name. The requester and users in member_ids with project access become members. New channels are starred for the requester unless star is false. The names "me" and "personal" are reserved.
 * @summary Create a channel
 */
export const TaskChannelsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const taskChannelsCreateBodyNameMax = 128

export const taskChannelsCreateBodyChannelTypeDefault = `public`
export const taskChannelsCreateBodyMemberIdsMax = 100

export const taskChannelsCreateBodyStarDefault = true

export const TaskChannelsCreateBody = () => zod.object({
    name: zod
        .string()
        .max(taskChannelsCreateBodyNameMax)
        .describe('Channel name, shown as #<name>. Uses lowercase letters and hyphens.'),
    channel_type: zod
        .enum(['public', 'private'])
        .describe('\* `public` - public\n\* `private` - private')
        .default(taskChannelsCreateBodyChannelTypeDefault)
        .describe(
            "Use 'public' for access by all project members. Use 'private' for access by channel members only. Defaults to 'public'. This endpoint cannot create personal #me spaces.\n\n\* `public` - public\n\* `private` - private"
        ),
    member_ids: zod
        .array(zod.number())
        .max(taskChannelsCreateBodyMemberIdsMax)
        .optional()
        .describe(
            'User IDs to add to a private channel. The requester is always a member. The endpoint ignores this field for public channels and skips users without project access.'
        ),
    star: zod
        .boolean()
        .default(taskChannelsCreateBodyStarDefault)
        .describe('Star a new channel for the requester. This field does not change stars on an existing channel.'),
})

/**
 * @summary Get a channel
 */
export const TaskChannelsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * The channel's latest CONTEXT.md instructions. A channel with no published instructions reads as a blank version 0 — publish against base_version 0 to create version 1.
 * @summary Get channel instructions
 */
export const TaskChannelsInstructionsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Publish a new version of the channel's CONTEXT.md instructions. Pass base_version (the version you read) so a concurrent edit is rejected with 409 instead of overwritten.
 * @summary Publish channel instructions
 */
export const TaskChannelsInstructionsUpdateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const taskChannelsInstructionsUpdateBodyContentMax = 100000

export const taskChannelsInstructionsUpdateBodyBaseVersionMin = 0

export const TaskChannelsInstructionsUpdateBody = () => zod
    .object({
        content: zod
            .string()
            .max(taskChannelsInstructionsUpdateBodyContentMax)
            .describe('The complete markdown instructions (CONTEXT.md) for the channel.'),
        base_version: zod
            .number()
            .min(taskChannelsInstructionsUpdateBodyBaseVersionMin)
            .nullish()
            .describe(
                'Optimistic-concurrency guard: the version the edit is based on (0 for a channel with no instructions yet). A stale base is rejected with 409; omit to publish unguarded.'
            ),
    })
    .describe('Request body for publishing a new instructions version.')

/**
 * Get a list of tasks for the current project, with optional filtering by origin product, stage, organization, repository, created_by, and the workflow (hog_flow_id) that created the task. By default, each row includes description. Pass basic=true for a summary row that omits description and includes description_preview, its first 1000 characters. Use the search parameter to match description text server-side.
 * @summary List tasks
 */
export const TasksListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const tasksListQueryAllTeamTasksDefault = false
export const tasksListQueryBasicDefault = false
export const tasksListQueryLimitDefault = 50
export const tasksListQueryLimitMax = 100

export const tasksListQueryOffsetDefault = 0
export const tasksListQueryOffsetMin = 0

export const TasksListQueryParams = () => zod.object({
    all_team_tasks: zod
        .boolean()
        .default(tasksListQueryAllTeamTasksDefault)
        .describe(
            'Local development only. With ph_debug=true, list all project tasks for debugging. Ignored outside local development.'
        ),
    archived: zod
        .enum(['true', 'false', 'all'])
        .optional()
        .describe(
            "Filter by archived state. Defaults to excluding archived tasks. Use 'true' to list only archived tasks, 'false' for the default, or 'all' to include both.\n\n\* `true` - true\n\* `false` - false\n\* `all` - all"
        ),
    basic: zod
        .boolean()
        .default(tasksListQueryBasicDefault)
        .describe(
            'With true, return basic list rows for summary surfaces: each row omits the full description and includes description_preview, its first 1000 characters. Defaults to false, which returns full task rows with description. The search parameter still matches description text server-side.'
        ),
    channel: zod.string().optional().describe("Filter tasks to a channel's feed."),
    ci_status: zod
        .enum(['passing', 'failing', 'pending', 'none'])
        .optional()
        .describe(
            "Filter tasks by the CI check rollup on their most recent run's pull request, as last observed from GitHub. 'none' means the PR has no checks.\n\n\* `passing` - passing\n\* `failing` - failing\n\* `pending` - pending\n\* `none` - none"
        ),
    client_provenance: zod
        .enum(['posthog_desktop'])
        .optional()
        .describe('Filter by the client that created the task\n\n\* `posthog_desktop` - PostHog Desktop'),
    commented_by: zod
        .number()
        .optional()
        .describe('Filter to tasks carrying a thread comment written by this user ID.'),
    created_by: zod.number().optional().describe('Filter by creator user ID'),
    exclude_origin_product: zod
        .enum([
            'onboarding',
            'error_tracking',
            'eval_clusters',
            'user_created',
            'slack',
            'support_queue',
            'session_summaries',
            'posthog_ai',
            'experiments',
            'signal_report',
            'signals_scout',
            'scout_suggestions',
            'support_reply',
            'hogdesk',
            'review_hog',
            'image_builder',
            'loop',
            'mcp_analytics',
            'signals_chat',
            'task_analysis',
            'workflow',
        ])
        .optional()
        .describe(
            'Exclude tasks with this origin product from the results\n\n\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `scout_suggestions` - Signals Scout Suggestions\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics\n\* `signals_chat` - Signals Chat\n\* `task_analysis` - Task Analysis\n\* `workflow` - Workflow'
        ),
    hog_flow_id: zod
        .string()
        .optional()
        .describe("Filter tasks to the runs spawned by this workflow's 'Create AI task' action."),
    internal: zod
        .enum(['true', 'false', 'all'])
        .optional()
        .describe(
            "Filter by the internal flag, which controls whether a task is shown by default, not whether it is accessible. Defaults to excluding internal tasks. Use 'all' to include both internal and user-facing tasks, or 'true' to list only internal tasks. All values are available to any team member; access stays governed by task visibility.\n\n\* `true` - true\n\* `false` - false\n\* `all` - all"
        ),
    limit: zod
        .number()
        .min(1)
        .max(tasksListQueryLimitMax)
        .default(tasksListQueryLimitDefault)
        .describe('Number of results to return per page.'),
    mentions: zod.number().optional().describe('Filter to tasks whose thread mentions this user ID.'),
    offset: zod
        .number()
        .min(tasksListQueryOffsetMin)
        .default(tasksListQueryOffsetDefault)
        .describe('The initial index from which to return the results.'),
    ordering: zod
        .enum(['-created_at', '-last_activity_at'])
        .optional()
        .describe(
            "Sort order. '-last_activity_at' is newest activity first, where activity means a thread message or a run starting, streaming, or finishing. Defaults to '-created_at'.\n\n\* `-created_at` - -created_at\n\* `-last_activity_at` - -last_activity_at"
        ),
    organization: zod.string().min(1).optional().describe('Filter by repository organization'),
    origin_product: zod.string().min(1).optional().describe('Filter by origin product'),
    pinned: zod.boolean().optional().describe('With true, only tasks the requesting user has pinned.'),
    pr_state: zod
        .enum(['open', 'draft', 'merged', 'closed'])
        .optional()
        .describe(
            "Filter tasks by the state of their most recent run's pull request, as last observed from GitHub (webhooks plus the CI follow-up snapshot).\n\n\* `open` - open\n\* `draft` - draft\n\* `merged` - merged\n\* `closed` - closed"
        ),
    repository: zod.string().min(1).optional().describe('Filter by repository name (can include org\/repo format)'),
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
            'Filter tasks by the status of their most recent run.\n\n\* `not_started` - not_started\n\* `queued` - queued\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `cancelled` - cancelled'
        ),
})

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const TasksCreateHeader = () => zod.object({
    'X-PostHog-Warm-Retry': zod
        .string()
        .optional()
        .describe('Retry token from a warm_run_activation_unavailable response; prevents creating a replacement run.'),
})

export const tasksCreateBodyTitleMax = 255

export const tasksCreateBodyRepositoryMax = 255

export const tasksCreateBodyRepositoriesItemMax = 255

export const tasksCreateBodyRepositoriesMax = 10

export const tasksCreateBodySignalReportTaskRelationshipMax = 200

export const tasksCreateBodyBranchMax = 255

export const tasksCreateBodyPendingUserArtifactIdsItemMax = 128

export const tasksCreateBodyStartRunDefault = false
export const tasksCreateBodySignalReportDiscussionQuestionMax = 4000

export const TasksCreateBody = () => zod.object({
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
            'slack',
            'support_queue',
            'session_summaries',
            'posthog_ai',
            'experiments',
            'signal_report',
            'signals_scout',
            'scout_suggestions',
            'support_reply',
            'hogdesk',
            'review_hog',
            'image_builder',
            'loop',
            'mcp_analytics',
            'signals_chat',
            'task_analysis',
            'workflow',
        ])
        .describe(
            '\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `scout_suggestions` - Signals Scout Suggestions\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics\n\* `signals_chat` - Signals Chat\n\* `task_analysis` - Task Analysis\n\* `workflow` - Workflow'
        )
        .optional()
        .describe(
            'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.\n\n\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `scout_suggestions` - Signals Scout Suggestions\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics\n\* `signals_chat` - Signals Chat\n\* `task_analysis` - Task Analysis\n\* `workflow` - Workflow'
        ),
    repository: zod
        .string()
        .max(tasksCreateBodyRepositoryMax)
        .nullish()
        .describe('Target GitHub repository in `organization\/repo` format (e.g. `posthog\/posthog-js`).'),
    repositories: zod
        .array(zod.string().max(tasksCreateBodyRepositoriesItemMax))
        .max(tasksCreateBodyRepositoriesMax)
        .optional()
        .describe('GitHub repositories available to this task, each in `organization\/repo` format.'),
    github_integration: zod.number().nullish().describe('GitHub integration for this task.'),
    github_user_integration: zod
        .string()
        .nullish()
        .describe('User-scoped GitHub integration to use for user-authored cloud runs.'),
    signal_report: zod.string().nullish().describe('Signal report this task implements, when created from a report.'),
    signal_report_task_relationship: zod
        .string()
        .max(tasksCreateBodySignalReportTaskRelationshipMax)
        .optional()
        .describe(
            "How the created task relates to the signal report (e.g. 'implementation', 'discussion'). Recorded as a signals task_run work-log entry; 'implementation' also opens the auto-start spend gate. Any routing-safe identifier (lowercase letters, numbers, '_', '-') is accepted except labels reserved for server-created tasks ('research', 'repo_selection', 'scout'). Non-implementation labels count toward the report's discussion task limit."
        ),
    json_schema: zod.unknown().optional().describe('JSON schema used to validate the output of the task.'),
    archived: zod.boolean().optional().describe('If true, the task is hidden from default list responses.'),
    ci_prompt: zod.string().nullish().describe('Custom prompt for CI fixes. If blank, a default prompt will be used.'),
    branch: zod
        .string()
        .max(tasksCreateBodyBranchMax)
        .nullish()
        .describe(
            "Base branch for the first run when start_run is true, or for matching a pre-warmed run. Omit to use the repository's default branch. Write-only and not persisted on the task."
        ),
    runtime_adapter: zod
        .union([zod.enum(['claude', 'codex']).describe('\* `claude` - claude\n\* `codex` - codex'), zod.null()])
        .optional()
        .describe(
            "Runtime adapter ('claude' or 'codex') for the first run when start_run is true, or for matching a pre-warmed run. A different adapter prevents warm reuse. Write-only and not persisted on the task.\n\n\* `claude` - claude\n\* `codex` - codex"
        ),
    model: zod
        .string()
        .nullish()
        .describe('LLM model for the first run when start_run is true, or for matching a pre-warmed run. Write-only.'),
    reasoning_effort: zod
        .union([
            zod
                .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                .describe(
                    '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Reasoning effort for the first run when start_run is true, or for matching a pre-warmed run. Write-only.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
        ),
    initial_permission_mode: zod
        .union([
            zod
                .enum(['default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto', 'read-only', 'full-access'])
                .describe(
                    '\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Agent permission mode for the first run when start_run is true, or for matching a pre-warmed run. Omit to match any warm permission mode. Write-only.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access'
        ),
    pending_user_message: zod
        .string()
        .nullish()
        .describe(
            'First user message when start_run is true or creation reuses a pre-warmed run. This message can differ from description. Ignored if creation does not start a run. Write-only and not persisted on the task.'
        ),
    pending_user_artifact_ids: zod
        .array(zod.string().max(tasksCreateBodyPendingUserArtifactIdsItemMax))
        .optional()
        .describe(
            "Run artifact ids (already uploaded to the pre-warmed Run) to attach to the forwarded first message when creation reuses that warm Run, e.g. skill bundles or file attachments. If any id is missing from the warm Run's manifest, warm reuse is skipped and the task is created cold. Ignored when no warm Run is matched. Not supported when start_run is true."
        ),
    auto_publish: zod
        .boolean()
        .nullish()
        .describe(
            'When true, the agent pushes its work and opens a draft pull request on completion without an explicit request. Applies when start_run is true or creation reuses a pre-warmed run. Resumed runs keep this setting. Ignored if creation does not start a run. Write-only and not persisted on the task.'
        ),
    channel: zod.string().nullish().describe('Channel this task is owned by (the channel it was kicked off in).'),
    start_run: zod
        .boolean()
        .default(tasksCreateBodyStartRunDefault)
        .describe("Start the task's first cloud run immediately after creation."),
    signal_report_discussion_question: zod
        .string()
        .max(tasksCreateBodySignalReportDiscussionQuestionMax)
        .optional()
        .describe(
            "Question to forward to the signal report's scout when creating a discussion task. Send an empty string when there is no question. Omit only for older clients that embed the question in the task description. Not persisted on the task."
        ),
    naming_source: zod
        .string()
        .optional()
        .describe(
            'Text the server generates the title from instead of `description`. Lets a client whose `description` is only an attachment summary (e.g. pasted text stored as a file) supply the real content for naming, so `description` (the prompt passed to the agent) stays unchanged. Not persisted.'
        ),
    sandbox_environment_id: zod
        .string()
        .nullish()
        .describe(
            'Sandbox environment for the first run when start_run is true, or for matching a pre-warmed run. Not persisted on the task.'
        ),
    custom_image_id: zod
        .string()
        .nullish()
        .describe(
            'Custom image for the first run when start_run is true, or for matching a pre-warmed run. Not persisted on the task.'
        ),
    runtime: zod
        .enum(['acp', 'pi'])
        .describe('\* `acp` - ACP\n\* `pi` - Pi')
        .optional()
        .describe(
            "Agent protocol and harness used for this task's runs. Defaults to ACP when omitted.\n\n\* `acp` - ACP\n\* `pi` - Pi"
        ),
})

/**
 * Retrieve a single task by ID.
 * @summary Get task
 */
export const tasksRetrievePathIdRegExp = new RegExp(
    '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

export const TasksRetrieveParams = () => zod.object({
    id: zod.string().regex(tasksRetrievePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create a new task run and kick off the workflow.
 * @summary Run task
 */
export const tasksRunCreatePathIdRegExp = new RegExp(
    '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

export const TasksRunCreateParams = () => zod.object({
    id: zod.string().regex(tasksRunCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const TasksRunCreateHeader = () => zod.object({
    'X-PostHog-Warm-Retry': zod
        .string()
        .optional()
        .describe('Retry token from a warm_run_activation_unavailable response; prevents creating a replacement run.'),
})

export const tasksRunCreateBodyOneImportedMcpServersItemNameMax = 64

export const tasksRunCreateBodyOneImportedMcpServersItemUrlMax = 2048

export const tasksRunCreateBodyOneImportedMcpServersItemHeadersItemNameMax = 256

export const tasksRunCreateBodyOneImportedMcpServersItemHeadersItemValueMax = 4096

export const tasksRunCreateBodyOneRelayedMcpServersItemNameMax = 64

export const tasksRunCreateBodyOneModeDefault = `background`
export const tasksRunCreateBodyOneBranchMax = 255

export const tasksRunCreateBodyOnePendingUserArtifactIdsItemMax = 128

export const tasksRunCreateBodyTwoImportedMcpServersItemNameMax = 64

export const tasksRunCreateBodyTwoImportedMcpServersItemUrlMax = 2048

export const tasksRunCreateBodyTwoImportedMcpServersItemHeadersItemNameMax = 256

export const tasksRunCreateBodyTwoImportedMcpServersItemHeadersItemValueMax = 4096

export const tasksRunCreateBodyTwoRelayedMcpServersItemNameMax = 64

export const tasksRunCreateBodyTwoModeDefault = `background`
export const tasksRunCreateBodyTwoBranchMax = 255

export const tasksRunCreateBodyTwoPendingUserArtifactIdsItemMax = 128

export const tasksRunCreateBodyThreeModeDefault = `background`
export const tasksRunCreateBodyThreeBranchMax = 255

export const TasksRunCreateBody = () => zod.union([
    zod
        .object({
            imported_mcp_servers: zod
                .array(
                    zod
                        .object({
                            type: zod.enum(['http', 'sse']).describe('\* `http` - http\n\* `sse` - sse'),
                            name: zod.string().max(tasksRunCreateBodyOneImportedMcpServersItemNameMax),
                            url: zod.url().max(tasksRunCreateBodyOneImportedMcpServersItemUrlMax),
                            headers: zod
                                .array(
                                    zod.object({
                                        name: zod
                                            .string()
                                            .max(tasksRunCreateBodyOneImportedMcpServersItemHeadersItemNameMax),
                                        value: zod
                                            .string()
                                            .max(tasksRunCreateBodyOneImportedMcpServersItemHeadersItemValueMax),
                                    })
                                )
                                .optional(),
                        })
                        .describe("One client-imported MCP server, in the agent server's --mcpServers entry shape.")
                )
                .nullish()
                .describe(
                    'Local url-based MCP servers from the creating client (PostHog Desktop) to make available inside the cloud sandbox. Header values are treated as credentials: stored encrypted and never returned by the API.'
                ),
            relayed_mcp_servers: zod
                .array(
                    zod
                        .object({
                            name: zod.string().max(tasksRunCreateBodyOneRelayedMcpServersItemNameMax),
                        })
                        .describe(
                            'One desktop-only MCP server relayed into the run — a name only, never configuration.'
                        )
                )
                .nullish()
                .describe(
                    'Names of desktop-only MCP servers the creating client (PostHog Desktop) relays into the cloud sandbox over the durable event\/command channel. Names only — the server configuration (command, env, URL, headers) never crosses the wire.'
                ),
            rtk_enabled: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether rtk command-output compression is enabled for this run. Omitted or null follows the server-side default (enabled); false opts this run out.'
                ),
            benjamin_enabled: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether the Benjamin-Plus token-efficiency instruction applies to this run. Omitted or null lets the server decide from the feature flag; true or false pins the choice for this run.'
                ),
            claude_model_access: zod
                .union([
                    zod
                        .enum(['posthog-gateway', 'own-subscription'])
                        .describe('\* `posthog-gateway` - posthog-gateway\n\* `own-subscription` - own-subscription'),
                    zod.null(),
                ])
                .optional()
                .describe(
                    "How the Claude runtime pays for model use. 'own-subscription' makes the sandbox request a Claude token from the creating PostHog Desktop at run start; the token is sent in flight and never stored on PostHog servers. If omitted or null, resumed runs keep their billing choice and new runs use the PostHog gateway.\n\n\* `posthog-gateway` - posthog-gateway\n\* `own-subscription` - own-subscription"
                ),
            mode: zod
                .enum(['interactive', 'background'])
                .describe('\* `interactive` - interactive\n\* `background` - background')
                .default(tasksRunCreateBodyOneModeDefault)
                .describe(
                    "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n\* `interactive` - interactive\n\* `background` - background"
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
            custom_image_id: zod
                .string()
                .optional()
                .describe(
                    "Optional custom base image for this cloud run's sandbox (Modal VM runtime only); takes precedence over the environment's image."
                ),
            pr_authorship_mode: zod
                .enum(['user', 'bot'])
                .describe('\* `user` - user\n\* `bot` - bot')
                .optional()
                .describe(
                    'Whether pull requests for this run should be authored by the user or the bot.\n\n\* `user` - user\n\* `bot` - bot'
                ),
            auto_publish: zod
                .boolean()
                .nullish()
                .describe(
                    'When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask.'
                ),
            run_source: zod
                .enum(['manual', 'signal_report', 'agent'])
                .describe('\* `manual` - manual\n\* `signal_report` - signal_report\n\* `agent` - agent')
                .optional()
                .describe(
                    'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n\* `manual` - manual\n\* `signal_report` - signal_report\n\* `agent` - agent'
                ),
            signal_report_id: zod
                .string()
                .optional()
                .describe('Optional signal report identifier when this run was started from Inbox.'),
            runtime_adapter: zod
                .enum(['claude'])
                .describe('\* `claude` - claude')
                .describe(
                    "Agent runtime adapter to launch for this run. Must be 'claude' for Claude runtimes.\n\n\* `claude` - claude"
                ),
            model: zod.string().describe('LLM model identifier to run in the Claude runtime.'),
            reasoning_effort: zod
                .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                .describe(
                    '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
                )
                .optional()
                .describe(
                    'Reasoning effort to request for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
                ),
            context_window: zod
                .enum(['200k', '1m'])
                .describe('\* `200k` - 200k\n\* `1m` - 1m')
                .optional()
                .describe(
                    'Context window size for models that support the 1M window.\n\n\* `200k` - 200k\n\* `1m` - 1m'
                ),
            fast_mode: zod.boolean().nullish().describe('Enable fast mode for models that support it.'),
            github_user_token: zod
                .string()
                .optional()
                .describe(
                    'Optional GitHub user token from PostHog Desktop for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens.'
                ),
            initial_permission_mode: zod
                .enum(['default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto'])
                .describe(
                    '\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto'
                )
                .optional()
                .describe(
                    'Initial permission mode for Claude runtimes.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto'
                ),
        })
        .describe('Request body for creating a new task run'),
    zod
        .object({
            imported_mcp_servers: zod
                .array(
                    zod
                        .object({
                            type: zod.enum(['http', 'sse']).describe('\* `http` - http\n\* `sse` - sse'),
                            name: zod.string().max(tasksRunCreateBodyTwoImportedMcpServersItemNameMax),
                            url: zod.url().max(tasksRunCreateBodyTwoImportedMcpServersItemUrlMax),
                            headers: zod
                                .array(
                                    zod.object({
                                        name: zod
                                            .string()
                                            .max(tasksRunCreateBodyTwoImportedMcpServersItemHeadersItemNameMax),
                                        value: zod
                                            .string()
                                            .max(tasksRunCreateBodyTwoImportedMcpServersItemHeadersItemValueMax),
                                    })
                                )
                                .optional(),
                        })
                        .describe("One client-imported MCP server, in the agent server's --mcpServers entry shape.")
                )
                .nullish()
                .describe(
                    'Local url-based MCP servers from the creating client (PostHog Desktop) to make available inside the cloud sandbox. Header values are treated as credentials: stored encrypted and never returned by the API.'
                ),
            relayed_mcp_servers: zod
                .array(
                    zod
                        .object({
                            name: zod.string().max(tasksRunCreateBodyTwoRelayedMcpServersItemNameMax),
                        })
                        .describe(
                            'One desktop-only MCP server relayed into the run — a name only, never configuration.'
                        )
                )
                .nullish()
                .describe(
                    'Names of desktop-only MCP servers the creating client (PostHog Desktop) relays into the cloud sandbox over the durable event\/command channel. Names only — the server configuration (command, env, URL, headers) never crosses the wire.'
                ),
            rtk_enabled: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether rtk command-output compression is enabled for this run. Omitted or null follows the server-side default (enabled); false opts this run out.'
                ),
            benjamin_enabled: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether the Benjamin-Plus token-efficiency instruction applies to this run. Omitted or null lets the server decide from the feature flag; true or false pins the choice for this run.'
                ),
            claude_model_access: zod
                .union([
                    zod
                        .enum(['posthog-gateway', 'own-subscription'])
                        .describe('\* `posthog-gateway` - posthog-gateway\n\* `own-subscription` - own-subscription'),
                    zod.null(),
                ])
                .optional()
                .describe(
                    "How the Claude runtime pays for model use. 'own-subscription' makes the sandbox request a Claude token from the creating PostHog Desktop at run start; the token is sent in flight and never stored on PostHog servers. If omitted or null, resumed runs keep their billing choice and new runs use the PostHog gateway.\n\n\* `posthog-gateway` - posthog-gateway\n\* `own-subscription` - own-subscription"
                ),
            mode: zod
                .enum(['interactive', 'background'])
                .describe('\* `interactive` - interactive\n\* `background` - background')
                .default(tasksRunCreateBodyTwoModeDefault)
                .describe(
                    "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n\* `interactive` - interactive\n\* `background` - background"
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
            custom_image_id: zod
                .string()
                .optional()
                .describe(
                    "Optional custom base image for this cloud run's sandbox (Modal VM runtime only); takes precedence over the environment's image."
                ),
            pr_authorship_mode: zod
                .enum(['user', 'bot'])
                .describe('\* `user` - user\n\* `bot` - bot')
                .optional()
                .describe(
                    'Whether pull requests for this run should be authored by the user or the bot.\n\n\* `user` - user\n\* `bot` - bot'
                ),
            auto_publish: zod
                .boolean()
                .nullish()
                .describe(
                    'When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask.'
                ),
            run_source: zod
                .enum(['manual', 'signal_report', 'agent'])
                .describe('\* `manual` - manual\n\* `signal_report` - signal_report\n\* `agent` - agent')
                .optional()
                .describe(
                    'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n\* `manual` - manual\n\* `signal_report` - signal_report\n\* `agent` - agent'
                ),
            signal_report_id: zod
                .string()
                .optional()
                .describe('Optional signal report identifier when this run was started from Inbox.'),
            runtime_adapter: zod
                .enum(['codex'])
                .describe('\* `codex` - codex')
                .describe(
                    "Agent runtime adapter to launch for this run. Must be 'codex' for Codex runtimes.\n\n\* `codex` - codex"
                ),
            model: zod.string().describe('LLM model identifier to run in the Codex runtime.'),
            reasoning_effort: zod
                .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                .describe(
                    '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
                )
                .optional()
                .describe(
                    'Reasoning effort to request for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
                ),
            context_window: zod
                .enum(['200k', '1m'])
                .describe('\* `200k` - 200k\n\* `1m` - 1m')
                .optional()
                .describe(
                    'Context window size for models that support the 1M window.\n\n\* `200k` - 200k\n\* `1m` - 1m'
                ),
            fast_mode: zod.boolean().nullish().describe('Enable fast mode for models that support it.'),
            github_user_token: zod
                .string()
                .optional()
                .describe(
                    'Optional GitHub user token from PostHog Desktop for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens.'
                ),
            initial_permission_mode: zod
                .enum(['plan', 'auto', 'read-only', 'full-access'])
                .describe(
                    '\* `plan` - plan\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access'
                )
                .optional()
                .describe(
                    'Initial permission mode for Codex runtimes.\n\n\* `plan` - plan\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access'
                ),
        })
        .describe('Request body for creating a new task run'),
    zod.object({
        mode: zod
            .enum(['interactive', 'background'])
            .describe('\* `interactive` - interactive\n\* `background` - background')
            .default(tasksRunCreateBodyThreeModeDefault)
            .describe(
                "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n\* `interactive` - interactive\n\* `background` - background"
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
        custom_image_id: zod
            .string()
            .optional()
            .describe(
                "Optional custom base image for this cloud run's sandbox (Modal VM runtime only); takes precedence over the environment's image."
            ),
        pr_authorship_mode: zod
            .enum(['user', 'bot'])
            .describe('\* `user` - user\n\* `bot` - bot')
            .optional()
            .describe(
                'Whether pull requests for this run should be authored by the user or the bot.\n\n\* `user` - user\n\* `bot` - bot'
            ),
        run_source: zod
            .enum(['manual', 'signal_report', 'agent'])
            .describe('\* `manual` - manual\n\* `signal_report` - signal_report\n\* `agent` - agent')
            .optional()
            .describe(
                'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n\* `manual` - manual\n\* `signal_report` - signal_report\n\* `agent` - agent'
            ),
        signal_report_id: zod
            .string()
            .optional()
            .describe('Optional signal report identifier when this run was started from Inbox.'),
        github_user_token: zod
            .string()
            .optional()
            .describe(
                'Optional GitHub user token from PostHog Desktop for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens.'
            ),
    }),
])

/**
 * Get a list of runs for a specific task.
 * @summary List task runs
 */
export const TasksRunsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    task_id: zod.string(),
})

export const tasksRunsListQueryLimitDefault = 50
export const tasksRunsListQueryLimitMax = 100

export const tasksRunsListQueryOffsetDefault = 0
export const tasksRunsListQueryOffsetMin = 0

export const TasksRunsListQueryParams = () => zod.object({
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
export const TasksRunsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    task_id: zod.string(),
})

/**
 * Fetch session log entries for a task run with optional filtering by timestamp, event type, and limit.
 * @summary Get filtered task run session logs
 */
export const TasksRunsSessionLogsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    task_id: zod.string(),
})

export const tasksRunsSessionLogsRetrieveQueryLimitDefault = 1000
export const tasksRunsSessionLogsRetrieveQueryLimitMax = 5000

export const tasksRunsSessionLogsRetrieveQueryOffsetDefault = 0
export const tasksRunsSessionLogsRetrieveQueryOffsetMin = 0

export const TasksRunsSessionLogsRetrieveQueryParams = () => zod.object({
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

/**
 * Retrieve your per-project default AI run preferences, plus the resolved defaults a new run will use when no explicit runtime selection is sent (your preference over the project default).
 */
export const TasksMeConfigListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const TasksMeConfigListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Set your per-project default AI run preferences; they override the project default wholesale. Send all fields as null to clear and inherit the project default.
 */
export const TasksMeConfigCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const TasksMeConfigCreateBody = () => zod
    .object({
        runtime_adapter: zod
            .union([zod.enum(['claude', 'codex']).describe('\* `claude` - claude\n\* `codex` - codex'), zod.null()])
            .optional()
            .describe(
                "Default agent runtime adapter for new task runs. Use 'claude' for the Claude runtime or 'codex' for the Codex runtime. Must be set together with `model`.\n\n\* `claude` - claude\n\* `codex` - codex"
            ),
        model: zod
            .string()
            .nullish()
            .describe('Default LLM model identifier for new task runs. Must be set together with `runtime_adapter`.'),
        reasoning_effort: zod
            .union([
                zod
                    .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                    .describe(
                        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Default reasoning effort for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
            ),
    })
    .describe(
        'The default AI run triple stored at team or user level.\n\nWrite payload for the tasks config endpoints and the `ai_run_preferences` block of\ntheir responses. `runtime_adapter` and `model` must be set together; send all three\nas null to clear a stored preference.'
    )

/**
 * Retrieve the project-wide default AI run preferences for task runs.
 */
export const TasksConfigListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const TasksConfigListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Set the project-wide default AI run preferences applied to task runs created without an explicit runtime selection. Send all fields as null to clear.
 */
export const TasksConfigCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const TasksConfigCreateBody = () => zod
    .object({
        runtime_adapter: zod
            .union([zod.enum(['claude', 'codex']).describe('\* `claude` - claude\n\* `codex` - codex'), zod.null()])
            .optional()
            .describe(
                "Default agent runtime adapter for new task runs. Use 'claude' for the Claude runtime or 'codex' for the Codex runtime. Must be set together with `model`.\n\n\* `claude` - claude\n\* `codex` - codex"
            ),
        model: zod
            .string()
            .nullish()
            .describe('Default LLM model identifier for new task runs. Must be set together with `runtime_adapter`.'),
        reasoning_effort: zod
            .union([
                zod
                    .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                    .describe(
                        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Default reasoning effort for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
            ),
    })
    .describe(
        'The default AI run triple stored at team or user level.\n\nWrite payload for the tasks config endpoints and the `ai_run_preferences` block of\ntheir responses. `runtime_adapter` and `model` must be set together; send all three\nas null to clear a stored preference.'
    )

/**
 * Return the models a task run may use, with the reasoning efforts each one supports. Derived from the live LLM gateway catalogue, so a newly released model appears without a client change. An empty list means the gateway is unreachable — clients should fall back to their own default rather than treating it as 'no models exist'.
 * @summary List available models
 */
export const TasksModelsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
