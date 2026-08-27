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
 * API for managing loops — named, cloud-executed agent automations triggered by
 * schedule, GitHub events or authenticated API calls. See `products/tasks/docs/LOOPS.md`.
 * @summary Create a loop
 */
export const loopsCreateBodyNameMax = 400

export const loopsCreateBodyDescriptionDefault = ``
export const loopsCreateBodyTakeOwnershipDefault = false
export const loopsCreateBodyVisibilityDefault = `personal`
export const loopsCreateBodyModelDefault = ``
export const loopsCreateBodyRepositoriesItemFullNameMax = 255

export const loopsCreateBodyRepositoriesMax = 1

export const loopsCreateBodyEnabledDefault = true
export const loopsCreateBodyOverlapPolicyDefault = `skip`
export const loopsCreateBodyBehaviorsOneCreatePrsDefault = false
export const loopsCreateBodyBehaviorsOneWatchCiDefault = false
export const loopsCreateBodyBehaviorsOneFixReviewCommentsDefault = false
export const loopsCreateBodyBehaviorsOneMaxFixIterationsDefault = 3
export const loopsCreateBodyBehaviorsOneMaxFixIterationsMin = 0
export const loopsCreateBodyBehaviorsOneMaxFixIterationsMax = 10

export const loopsCreateBodyConnectorsOnePosthogMcpScopesDefault = `read_only`
export const loopsCreateBodyNotificationsOnePushOneEnabledDefault = false
export const loopsCreateBodyNotificationsOneEmailOneEnabledDefault = false
export const loopsCreateBodyNotificationsOneSlackOneEnabledDefault = false
export const loopsCreateBodyContextTargetOneNameMax = 128

export const loopsCreateBodyContextTargetOneOutputsOnePostToFeedDefault = false
export const loopsCreateBodyContextTargetOneOutputsOneUpdateContextDefault = false
export const loopsCreateBodyTriggersItemEnabledDefault = true

export const LoopsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(loopsCreateBodyNameMax).describe('Display name for the loop.'),
        description: zod
            .string()
            .default(loopsCreateBodyDescriptionDefault)
            .describe('Free-form description of what this loop does.'),
        take_ownership: zod
            .boolean()
            .default(loopsCreateBodyTakeOwnershipDefault)
            .describe(
                'On a team loop, claim ownership as part of this update so you can edit identity-bearing config (instructions, model, triggers, ...) that only the owner may change. Ignored on personal loops and on create.'
            ),
        visibility: zod
            .enum(['personal', 'team'])
            .describe('\* `personal` - personal\n\* `team` - team')
            .default(loopsCreateBodyVisibilityDefault)
            .describe(
                '`personal` (owner-only) or `team` (visible and fireable by any team member).\n\n\* `personal` - personal\n\* `team` - team'
            ),
        instructions: zod.string().describe('The prompt delivered to the agent on every run.'),
        runtime_adapter: zod
            .enum(['claude', 'codex'])
            .describe('\* `claude` - claude\n\* `codex` - codex')
            .describe("Runtime adapter: 'claude' or 'codex'.\n\n\* `claude` - claude\n\* `codex` - codex"),
        model: zod
            .string()
            .default(loopsCreateBodyModelDefault)
            .describe(
                "LLM model identifier, validated against `runtime_adapter`'s catalog. Leave blank to let PostHog pick a sensible default at run time."
            ),
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
                "Reasoning effort, validated against `runtime_adapter`\/`model`'s supported set.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode"
            ),
        repositories: zod
            .array(
                zod.object({
                    github_integration_id: zod
                        .number()
                        .describe('GitHub integration id this repository is accessed through.'),
                    full_name: zod
                        .string()
                        .max(loopsCreateBodyRepositoriesItemFullNameMax)
                        .describe('Repository in `organization\/repo` format, e.g. `posthog\/posthog`.'),
                })
            )
            .max(loopsCreateBodyRepositoriesMax)
            .optional()
            .describe(
                'Repositories this loop operates on, ordered. Capped at 1 until multi-repo execution ships. May be empty for report-only loops.'
            ),
        sandbox_environment: zod
            .uuid()
            .nullish()
            .describe('Sandbox environment carrying encrypted env vars and the network allowlist into every run.'),
        enabled: zod
            .boolean()
            .default(loopsCreateBodyEnabledDefault)
            .describe("Whether the loop's triggers are active. Pausing disables all triggers."),
        overlap_policy: zod
            .enum(['skip', 'allow', 'cancel_previous'])
            .describe('\* `skip` - skip\n\* `allow` - allow\n\* `cancel_previous` - cancel_previous')
            .default(loopsCreateBodyOverlapPolicyDefault)
            .describe(
                "What happens when a trigger fires while a run is already active: 'skip', 'allow', or 'cancel_previous'.\n\n\* `skip` - skip\n\* `allow` - allow\n\* `cancel_previous` - cancel_previous"
            ),
        behaviors: zod
            .object({
                create_prs: zod
                    .boolean()
                    .default(loopsCreateBodyBehaviorsOneCreatePrsDefault)
                    .describe('Whether the agent may push branches and open PRs. False makes this a report-only loop.'),
                watch_ci: zod
                    .boolean()
                    .default(loopsCreateBodyBehaviorsOneWatchCiDefault)
                    .describe('Whether to watch CI on loop-created PRs and report status.'),
                fix_review_comments: zod
                    .boolean()
                    .default(loopsCreateBodyBehaviorsOneFixReviewCommentsDefault)
                    .describe('Whether to automatically address review comments on loop-created PRs.'),
                max_fix_iterations: zod
                    .number()
                    .min(loopsCreateBodyBehaviorsOneMaxFixIterationsMin)
                    .max(loopsCreateBodyBehaviorsOneMaxFixIterationsMax)
                    .default(loopsCreateBodyBehaviorsOneMaxFixIterationsDefault)
                    .describe('Ceiling on automatic CI\/review-comment fix iterations, capped at 10.'),
            })
            .optional()
            .describe('PR \/ CI-follow-up behavior configuration.'),
        connectors: zod
            .object({
                mcp_installation_ids: zod
                    .array(zod.string())
                    .optional()
                    .describe("MCP Store installation ids (Slack, Linear, etc.) available to this loop's runs."),
                posthog_mcp_scopes: zod
                    .enum(['read_only', 'full'])
                    .describe('\* `read_only` - read_only\n\* `full` - full')
                    .default(loopsCreateBodyConnectorsOnePosthogMcpScopesDefault)
                    .describe(
                        "Scope of the PostHog MCP access injected into this loop's runs.\n\n\* `read_only` - read_only\n\* `full` - full"
                    ),
            })
            .optional()
            .describe("MCP connector configuration for this loop's runs."),
        notifications: zod
            .object({
                push: zod
                    .object({
                        enabled: zod
                            .boolean()
                            .default(loopsCreateBodyNotificationsOnePushOneEnabledDefault)
                            .describe('Whether this channel is active.'),
                        events: zod
                            .array(
                                zod
                                    .enum(['run_completed', 'run_failed', 'pr_created', 'needs_attention'])
                                    .describe(
                                        '\* `run_completed` - run_completed\n\* `run_failed` - run_failed\n\* `pr_created` - pr_created\n\* `needs_attention` - needs_attention'
                                    )
                            )
                            .optional()
                            .describe(
                                'Event kinds this channel notifies on. One or more of: run_completed, run_failed, pr_created, needs_attention.'
                            ),
                        params: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe("Channel-specific parameters, e.g. Slack's `integration_id` and `channel`."),
                    })
                    .optional()
                    .describe('Push notification settings.'),
                email: zod
                    .object({
                        enabled: zod
                            .boolean()
                            .default(loopsCreateBodyNotificationsOneEmailOneEnabledDefault)
                            .describe('Whether this channel is active.'),
                        events: zod
                            .array(
                                zod
                                    .enum(['run_completed', 'run_failed', 'pr_created', 'needs_attention'])
                                    .describe(
                                        '\* `run_completed` - run_completed\n\* `run_failed` - run_failed\n\* `pr_created` - pr_created\n\* `needs_attention` - needs_attention'
                                    )
                            )
                            .optional()
                            .describe(
                                'Event kinds this channel notifies on. One or more of: run_completed, run_failed, pr_created, needs_attention.'
                            ),
                        params: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe("Channel-specific parameters, e.g. Slack's `integration_id` and `channel`."),
                    })
                    .optional()
                    .describe('Email notification settings.'),
                slack: zod
                    .object({
                        enabled: zod
                            .boolean()
                            .default(loopsCreateBodyNotificationsOneSlackOneEnabledDefault)
                            .describe('Whether this channel is active.'),
                        events: zod
                            .array(
                                zod
                                    .enum(['run_completed', 'run_failed', 'pr_created', 'needs_attention'])
                                    .describe(
                                        '\* `run_completed` - run_completed\n\* `run_failed` - run_failed\n\* `pr_created` - pr_created\n\* `needs_attention` - needs_attention'
                                    )
                            )
                            .optional()
                            .describe(
                                'Event kinds this channel notifies on. One or more of: run_completed, run_failed, pr_created, needs_attention.'
                            ),
                        params: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe("Channel-specific parameters, e.g. Slack's `integration_id` and `channel`."),
                    })
                    .optional()
                    .describe('Slack notification settings.'),
            })
            .optional()
            .describe('Per-channel notification configuration.'),
        context_target: zod
            .union([
                zod.object({
                    channel_id: zod.string().describe('Id of the channel (context) this loop is attached to.'),
                    name: zod
                        .string()
                        .max(loopsCreateBodyContextTargetOneNameMax)
                        .describe("Display name of the context, shown in the loop's publish prompt."),
                    outputs: zod
                        .object({
                            post_to_feed: zod
                                .boolean()
                                .default(loopsCreateBodyContextTargetOneOutputsOnePostToFeedDefault)
                                .describe(
                                    "Whether each run is filed into the context's feed as a card (sets the run's channel)."
                                ),
                            update_context: zod
                                .boolean()
                                .default(loopsCreateBodyContextTargetOneOutputsOneUpdateContextDefault)
                                .describe(
                                    "Whether each run reads and republishes the context's context.md to reflect the latest state."
                                ),
                            canvas_id: zod
                                .string()
                                .nullish()
                                .describe(
                                    'Id of a canvas in this context the loop keeps up to date each run, or null to maintain none.'
                                ),
                        })
                        .optional()
                        .describe('What the loop maintains in this context each run.'),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                'Context (channel) this loop is attached to, or null to detach. Drives feed placement and the context.md \/ canvas it keeps up to date.'
            ),
        triggers: zod
            .array(
                zod.object({
                    id: zod
                        .uuid()
                        .optional()
                        .describe('Existing trigger id to update in place. Omit to create a new trigger.'),
                    type: zod
                        .enum(['schedule', 'github', 'api'])
                        .describe('\* `schedule` - schedule\n\* `github` - github\n\* `api` - api')
                        .describe(
                            'Trigger type: `schedule` (cron or one-time), `github` (repo webhook events), or `api` (POST to `trigger\/`).\n\n\* `schedule` - schedule\n\* `github` - github\n\* `api` - api'
                        ),
                    enabled: zod
                        .boolean()
                        .default(loopsCreateBodyTriggersItemEnabledDefault)
                        .describe('Whether this trigger is active. Disabling pauses only this trigger.'),
                    config: zod
                        .unknown()
                        .optional()
                        .describe(
                            'Trigger configuration, shape validated per `type`: schedule takes `{cron_expression, timezone}` or `{run_at}` for a one-time run; github takes `{github_integration_id, repository, events, filters}` where `events` is one or more of `issues`, `issue_comment`, `pull_request`, `push` (`event.action` shorthand like `issues.opened` is folded into an `actions` filter, one event per trigger) and `filters` takes `{actions, branches, labels, payload}`. Use `actions` for the event action; `payload` is for anything else in the webhook body, as a list of `{path, equals}` conditions where `path` is a dot-path of object keys and `equals` is a string or list of strings, e.g. `[{\"path\": \"requested_team.slug\", \"equals\": \"team-security\"}]` to run only when that team is asked to review. All filters must match. API triggers take no config.'
                        ),
                })
            )
            .optional()
            .describe(
                'Full desired trigger list, id-stable: entries with a matching `id` are updated in place, entries without one are created, and existing triggers absent from this list are deleted. Omit the field entirely to leave triggers untouched. At most 25 triggers per loop.'
            ),
    })
    .describe(
        'Request body for creating or updating a loop. Field required\/default semantics match\nthe `Loop` model; partial updates only touch keys present in the payload.'
    )

/**
 * Partial update. Identity-bearing fields (instructions, repositories, connectors, behaviors, model config, triggers) are owner-only on team loops; name, description, notifications and enable/pause are editable by any team member.
 * @summary Update a loop
 */
export const loopsPartialUpdateBodyNameMax = 400

export const loopsPartialUpdateBodyDescriptionDefault = ``
export const loopsPartialUpdateBodyTakeOwnershipDefault = false
export const loopsPartialUpdateBodyVisibilityDefault = `personal`
export const loopsPartialUpdateBodyModelDefault = ``
export const loopsPartialUpdateBodyRepositoriesItemFullNameMax = 255

export const loopsPartialUpdateBodyRepositoriesMax = 1

export const loopsPartialUpdateBodyEnabledDefault = true
export const loopsPartialUpdateBodyOverlapPolicyDefault = `skip`
export const loopsPartialUpdateBodyBehaviorsOneCreatePrsDefault = false
export const loopsPartialUpdateBodyBehaviorsOneWatchCiDefault = false
export const loopsPartialUpdateBodyBehaviorsOneFixReviewCommentsDefault = false
export const loopsPartialUpdateBodyBehaviorsOneMaxFixIterationsDefault = 3
export const loopsPartialUpdateBodyBehaviorsOneMaxFixIterationsMin = 0
export const loopsPartialUpdateBodyBehaviorsOneMaxFixIterationsMax = 10

export const loopsPartialUpdateBodyConnectorsOnePosthogMcpScopesDefault = `read_only`
export const loopsPartialUpdateBodyNotificationsOnePushOneEnabledDefault = false
export const loopsPartialUpdateBodyNotificationsOneEmailOneEnabledDefault = false
export const loopsPartialUpdateBodyNotificationsOneSlackOneEnabledDefault = false
export const loopsPartialUpdateBodyContextTargetOneNameMax = 128

export const loopsPartialUpdateBodyContextTargetOneOutputsOnePostToFeedDefault = false
export const loopsPartialUpdateBodyContextTargetOneOutputsOneUpdateContextDefault = false
export const loopsPartialUpdateBodyTriggersItemEnabledDefault = true

export const LoopsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(loopsPartialUpdateBodyNameMax).optional().describe('Display name for the loop.'),
        description: zod
            .string()
            .default(loopsPartialUpdateBodyDescriptionDefault)
            .describe('Free-form description of what this loop does.'),
        take_ownership: zod
            .boolean()
            .default(loopsPartialUpdateBodyTakeOwnershipDefault)
            .describe(
                'On a team loop, claim ownership as part of this update so you can edit identity-bearing config (instructions, model, triggers, ...) that only the owner may change. Ignored on personal loops and on create.'
            ),
        visibility: zod
            .enum(['personal', 'team'])
            .describe('\* `personal` - personal\n\* `team` - team')
            .default(loopsPartialUpdateBodyVisibilityDefault)
            .describe(
                '`personal` (owner-only) or `team` (visible and fireable by any team member).\n\n\* `personal` - personal\n\* `team` - team'
            ),
        instructions: zod.string().optional().describe('The prompt delivered to the agent on every run.'),
        runtime_adapter: zod
            .enum(['claude', 'codex'])
            .describe('\* `claude` - claude\n\* `codex` - codex')
            .optional()
            .describe("Runtime adapter: 'claude' or 'codex'.\n\n\* `claude` - claude\n\* `codex` - codex"),
        model: zod
            .string()
            .default(loopsPartialUpdateBodyModelDefault)
            .describe(
                "LLM model identifier, validated against `runtime_adapter`'s catalog. Leave blank to let PostHog pick a sensible default at run time."
            ),
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
                "Reasoning effort, validated against `runtime_adapter`\/`model`'s supported set.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode"
            ),
        repositories: zod
            .array(
                zod.object({
                    github_integration_id: zod
                        .number()
                        .describe('GitHub integration id this repository is accessed through.'),
                    full_name: zod
                        .string()
                        .max(loopsPartialUpdateBodyRepositoriesItemFullNameMax)
                        .describe('Repository in `organization\/repo` format, e.g. `posthog\/posthog`.'),
                })
            )
            .max(loopsPartialUpdateBodyRepositoriesMax)
            .optional()
            .describe(
                'Repositories this loop operates on, ordered. Capped at 1 until multi-repo execution ships. May be empty for report-only loops.'
            ),
        sandbox_environment: zod
            .uuid()
            .nullish()
            .describe('Sandbox environment carrying encrypted env vars and the network allowlist into every run.'),
        enabled: zod
            .boolean()
            .default(loopsPartialUpdateBodyEnabledDefault)
            .describe("Whether the loop's triggers are active. Pausing disables all triggers."),
        overlap_policy: zod
            .enum(['skip', 'allow', 'cancel_previous'])
            .describe('\* `skip` - skip\n\* `allow` - allow\n\* `cancel_previous` - cancel_previous')
            .default(loopsPartialUpdateBodyOverlapPolicyDefault)
            .describe(
                "What happens when a trigger fires while a run is already active: 'skip', 'allow', or 'cancel_previous'.\n\n\* `skip` - skip\n\* `allow` - allow\n\* `cancel_previous` - cancel_previous"
            ),
        behaviors: zod
            .object({
                create_prs: zod
                    .boolean()
                    .default(loopsPartialUpdateBodyBehaviorsOneCreatePrsDefault)
                    .describe('Whether the agent may push branches and open PRs. False makes this a report-only loop.'),
                watch_ci: zod
                    .boolean()
                    .default(loopsPartialUpdateBodyBehaviorsOneWatchCiDefault)
                    .describe('Whether to watch CI on loop-created PRs and report status.'),
                fix_review_comments: zod
                    .boolean()
                    .default(loopsPartialUpdateBodyBehaviorsOneFixReviewCommentsDefault)
                    .describe('Whether to automatically address review comments on loop-created PRs.'),
                max_fix_iterations: zod
                    .number()
                    .min(loopsPartialUpdateBodyBehaviorsOneMaxFixIterationsMin)
                    .max(loopsPartialUpdateBodyBehaviorsOneMaxFixIterationsMax)
                    .default(loopsPartialUpdateBodyBehaviorsOneMaxFixIterationsDefault)
                    .describe('Ceiling on automatic CI\/review-comment fix iterations, capped at 10.'),
            })
            .optional()
            .describe('PR \/ CI-follow-up behavior configuration.'),
        connectors: zod
            .object({
                mcp_installation_ids: zod
                    .array(zod.string())
                    .optional()
                    .describe("MCP Store installation ids (Slack, Linear, etc.) available to this loop's runs."),
                posthog_mcp_scopes: zod
                    .enum(['read_only', 'full'])
                    .describe('\* `read_only` - read_only\n\* `full` - full')
                    .default(loopsPartialUpdateBodyConnectorsOnePosthogMcpScopesDefault)
                    .describe(
                        "Scope of the PostHog MCP access injected into this loop's runs.\n\n\* `read_only` - read_only\n\* `full` - full"
                    ),
            })
            .optional()
            .describe("MCP connector configuration for this loop's runs."),
        notifications: zod
            .object({
                push: zod
                    .object({
                        enabled: zod
                            .boolean()
                            .default(loopsPartialUpdateBodyNotificationsOnePushOneEnabledDefault)
                            .describe('Whether this channel is active.'),
                        events: zod
                            .array(
                                zod
                                    .enum(['run_completed', 'run_failed', 'pr_created', 'needs_attention'])
                                    .describe(
                                        '\* `run_completed` - run_completed\n\* `run_failed` - run_failed\n\* `pr_created` - pr_created\n\* `needs_attention` - needs_attention'
                                    )
                            )
                            .optional()
                            .describe(
                                'Event kinds this channel notifies on. One or more of: run_completed, run_failed, pr_created, needs_attention.'
                            ),
                        params: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe("Channel-specific parameters, e.g. Slack's `integration_id` and `channel`."),
                    })
                    .optional()
                    .describe('Push notification settings.'),
                email: zod
                    .object({
                        enabled: zod
                            .boolean()
                            .default(loopsPartialUpdateBodyNotificationsOneEmailOneEnabledDefault)
                            .describe('Whether this channel is active.'),
                        events: zod
                            .array(
                                zod
                                    .enum(['run_completed', 'run_failed', 'pr_created', 'needs_attention'])
                                    .describe(
                                        '\* `run_completed` - run_completed\n\* `run_failed` - run_failed\n\* `pr_created` - pr_created\n\* `needs_attention` - needs_attention'
                                    )
                            )
                            .optional()
                            .describe(
                                'Event kinds this channel notifies on. One or more of: run_completed, run_failed, pr_created, needs_attention.'
                            ),
                        params: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe("Channel-specific parameters, e.g. Slack's `integration_id` and `channel`."),
                    })
                    .optional()
                    .describe('Email notification settings.'),
                slack: zod
                    .object({
                        enabled: zod
                            .boolean()
                            .default(loopsPartialUpdateBodyNotificationsOneSlackOneEnabledDefault)
                            .describe('Whether this channel is active.'),
                        events: zod
                            .array(
                                zod
                                    .enum(['run_completed', 'run_failed', 'pr_created', 'needs_attention'])
                                    .describe(
                                        '\* `run_completed` - run_completed\n\* `run_failed` - run_failed\n\* `pr_created` - pr_created\n\* `needs_attention` - needs_attention'
                                    )
                            )
                            .optional()
                            .describe(
                                'Event kinds this channel notifies on. One or more of: run_completed, run_failed, pr_created, needs_attention.'
                            ),
                        params: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe("Channel-specific parameters, e.g. Slack's `integration_id` and `channel`."),
                    })
                    .optional()
                    .describe('Slack notification settings.'),
            })
            .optional()
            .describe('Per-channel notification configuration.'),
        context_target: zod
            .union([
                zod.object({
                    channel_id: zod.string().describe('Id of the channel (context) this loop is attached to.'),
                    name: zod
                        .string()
                        .max(loopsPartialUpdateBodyContextTargetOneNameMax)
                        .describe("Display name of the context, shown in the loop's publish prompt."),
                    outputs: zod
                        .object({
                            post_to_feed: zod
                                .boolean()
                                .default(loopsPartialUpdateBodyContextTargetOneOutputsOnePostToFeedDefault)
                                .describe(
                                    "Whether each run is filed into the context's feed as a card (sets the run's channel)."
                                ),
                            update_context: zod
                                .boolean()
                                .default(loopsPartialUpdateBodyContextTargetOneOutputsOneUpdateContextDefault)
                                .describe(
                                    "Whether each run reads and republishes the context's context.md to reflect the latest state."
                                ),
                            canvas_id: zod
                                .string()
                                .nullish()
                                .describe(
                                    'Id of a canvas in this context the loop keeps up to date each run, or null to maintain none.'
                                ),
                        })
                        .optional()
                        .describe('What the loop maintains in this context each run.'),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                'Context (channel) this loop is attached to, or null to detach. Drives feed placement and the context.md \/ canvas it keeps up to date.'
            ),
        triggers: zod
            .array(
                zod.object({
                    id: zod
                        .uuid()
                        .optional()
                        .describe('Existing trigger id to update in place. Omit to create a new trigger.'),
                    type: zod
                        .enum(['schedule', 'github', 'api'])
                        .describe('\* `schedule` - schedule\n\* `github` - github\n\* `api` - api')
                        .describe(
                            'Trigger type: `schedule` (cron or one-time), `github` (repo webhook events), or `api` (POST to `trigger\/`).\n\n\* `schedule` - schedule\n\* `github` - github\n\* `api` - api'
                        ),
                    enabled: zod
                        .boolean()
                        .default(loopsPartialUpdateBodyTriggersItemEnabledDefault)
                        .describe('Whether this trigger is active. Disabling pauses only this trigger.'),
                    config: zod
                        .unknown()
                        .optional()
                        .describe(
                            'Trigger configuration, shape validated per `type`: schedule takes `{cron_expression, timezone}` or `{run_at}` for a one-time run; github takes `{github_integration_id, repository, events, filters}` where `events` is one or more of `issues`, `issue_comment`, `pull_request`, `push` (`event.action` shorthand like `issues.opened` is folded into an `actions` filter, one event per trigger) and `filters` takes `{actions, branches, labels, payload}`. Use `actions` for the event action; `payload` is for anything else in the webhook body, as a list of `{path, equals}` conditions where `path` is a dot-path of object keys and `equals` is a string or list of strings, e.g. `[{\"path\": \"requested_team.slug\", \"equals\": \"team-security\"}]` to run only when that team is asked to review. All filters must match. API triggers take no config.'
                        ),
                })
            )
            .optional()
            .describe(
                'Full desired trigger list, id-stable: entries with a matching `id` are updated in place, entries without one are created, and existing triggers absent from this list are deleted. Omit the field entirely to leave triggers untouched. At most 25 triggers per loop.'
            ),
    })
    .describe(
        'Request body for creating or updating a loop. Field required\/default semantics match\nthe `Loop` model; partial updates only touch keys present in the payload.'
    )

/**
 * Dry run: renders the assembled instructions and trigger context for a supplied sample payload (or a synthetic schedule fire when omitted), without creating a task, run, or any other side effect.
 * @summary Preview a loop fire
 */
export const loopsPreviewCreateBodyTriggerTypeDefault = `schedule`

export const LoopsPreviewCreateBody = /* @__PURE__ */ zod.object({
    trigger_type: zod
        .enum(['schedule', 'github', 'api'])
        .describe('\* `schedule` - schedule\n\* `github` - github\n\* `api` - api')
        .default(loopsPreviewCreateBodyTriggerTypeDefault)
        .describe(
            'Trigger type to simulate. Defaults to a synthetic schedule fire.\n\n\* `schedule` - schedule\n\* `github` - github\n\* `api` - api'
        ),
    payload: zod
        .unknown()
        .optional()
        .describe('Sample trigger payload, e.g. a GitHub webhook body or an API trigger body, to render into context.'),
})

/**
 * Replaces the loop's attached skill bundles wholesale: zipped local skills whose contents are seeded into every fired run's sandbox. Send an empty list to detach every skill. Owner-only on team loops, like other identity-bearing configuration.
 * @summary Replace a loop's skill bundles
 */
export const loopsSkillBundlesUpdateBodyBundlesItemFileNameMax = 255

export const loopsSkillBundlesUpdateBodyBundlesItemSkillNameMax = 255

export const loopsSkillBundlesUpdateBodyBundlesItemContentSha256RegExp = new RegExp('^[a-f0-9]{64}$')

export const LoopsSkillBundlesUpdateBody = /* @__PURE__ */ zod
    .object({
        bundles: zod.array(
            zod
                .object({
                    file_name: zod
                        .string()
                        .max(loopsSkillBundlesUpdateBodyBundlesItemFileNameMax)
                        .describe('File name for the stored bundle, e.g. `my-skill.zip`.'),
                    skill_name: zod
                        .string()
                        .max(loopsSkillBundlesUpdateBodyBundlesItemSkillNameMax)
                        .describe('Name of the skill inside the bundle.'),
                    skill_source: zod
                        .enum(['user', 'repo', 'marketplace', 'codex'])
                        .describe(
                            '\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
                        )
                        .describe(
                            'Local source the bundle was built from, such as user or repo.\n\n\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
                        ),
                    content_sha256: zod
                        .string()
                        .regex(loopsSkillBundlesUpdateBodyBundlesItemContentSha256RegExp)
                        .describe('SHA-256 hex digest of the bundle bytes.'),
                    bundle_format: zod
                        .enum(['zip'])
                        .describe('\* `zip` - zip')
                        .describe('Archive format used for the bundle.\n\n\* `zip` - zip'),
                    content_base64: zod.string().describe('Base64-encoded bundle bytes.'),
                })
                .describe('One zipped local skill in a skill-bundle replace request.')
        ),
    })
    .describe(
        "Request body for replacing a loop's attached skill bundles wholesale. Send an empty\nlist to detach every skill."
    )

/**
 * Authenticated POST trigger for `type=api` triggers. Project secret API key auth (`loop:write` scope), project-wide. Request body (JSON, capped at 64 KB) becomes run context. Send an `Idempotency-Key` header to dedupe retries.
 * @summary Fire a loop externally
 */
export const LoopsTriggerCreateBody = /* @__PURE__ */ zod.record(zod.string(), zod.unknown())

/**
 * Create a draft custom image and start its interactive image-builder agent task. The returned builder_task_id points at the conversation.
 */
export const sandboxCustomImagesCreateBodyNameMax = 255

export const sandboxCustomImagesCreateBodyDescriptionDefault = ``
export const sandboxCustomImagesCreateBodyRepositoryMax = 255

export const sandboxCustomImagesCreateBodyPrivateDefault = false

export const SandboxCustomImagesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(sandboxCustomImagesCreateBodyNameMax).describe('Display name for the custom image.'),
        description: zod
            .string()
            .default(sandboxCustomImagesCreateBodyDescriptionDefault)
            .describe('What should go into the image; seeds the image-builder agent conversation.'),
        repository: zod
            .string()
            .max(sandboxCustomImagesCreateBodyRepositoryMax)
            .nullish()
            .describe(
                "Optional 'org\/repo' the builder session clones so it can verify the image brings up that repository's dependencies."
            ),
        private: zod
            .boolean()
            .default(sandboxCustomImagesCreateBodyPrivateDefault)
            .describe('If true, only you can see and use this image; otherwise the whole team can.'),
    })
    .describe('Request body for creating a custom sandbox base image.')

/**
 * Rename or update the description of a custom image. Only mutable metadata (name, description) is editable; the build spec and status are managed by the build flow.
 */
export const sandboxCustomImagesPartialUpdateBodyNameMax = 255

export const SandboxCustomImagesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(sandboxCustomImagesPartialUpdateBodyNameMax)
            .optional()
            .describe('New display name for the custom image. Omit to leave unchanged.'),
        description: zod
            .string()
            .optional()
            .describe('New description. Omit to leave unchanged; pass an empty string to clear it.'),
    })
    .describe('Request body for renaming \/ re-describing a custom sandbox base image.')

/**
 * Persist the image spec (from the request body or the builder agent's sandbox), run the security scan, and on pass build and publish the image.
 */
export const SandboxCustomImagesBuildCreateBody = /* @__PURE__ */ zod
    .object({
        spec_yaml: zod
            .string()
            .nullish()
            .describe(
                "Image spec YAML to build. When omitted, the spec is read from the builder agent's live sandbox."
            ),
    })
    .describe('Request body for scanning and building a custom sandbox base image.')

/**
 * API for managing sandbox environments that control network access for task runs.
 */
export const sandboxCreateBodyNameMax = 255

export const sandboxCreateBodyNetworkAccessLevelDefault = `full`
export const sandboxCreateBodyAllowedDomainsItemMax = 255

export const sandboxCreateBodyAllowedDomainsMax = 100

export const sandboxCreateBodyIncludeDefaultDomainsDefault = false
export const sandboxCreateBodyRepositoriesItemMax = 255

export const sandboxCreateBodyPrivateDefault = true

export const SandboxCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(sandboxCreateBodyNameMax).describe('Display name for the environment.'),
        network_access_level: zod
            .enum(['trusted', 'full', 'custom'])
            .describe('\* `trusted` - Trusted\n\* `full` - Full\n\* `custom` - Custom')
            .default(sandboxCreateBodyNetworkAccessLevelDefault)
            .describe(
                'Network access policy: trusted (default allowlist), full (unrestricted), or custom.\n\n\* `trusted` - Trusted\n\* `full` - Full\n\* `custom` - Custom'
            ),
        allowed_domains: zod
            .array(zod.string().max(sandboxCreateBodyAllowedDomainsItemMax))
            .max(sandboxCreateBodyAllowedDomainsMax)
            .optional()
            .describe('Allowed domains for custom network access.'),
        include_default_domains: zod
            .boolean()
            .default(sandboxCreateBodyIncludeDefaultDomainsDefault)
            .describe('Whether to include default trusted domains (GitHub, npm, PyPI).'),
        repositories: zod
            .array(zod.string().max(sandboxCreateBodyRepositoriesItemMax))
            .optional()
            .describe('Repositories this environment applies to (format: org\/repo).'),
        environment_variables: zod
            .unknown()
            .optional()
            .describe('Encrypted environment variables (write-only, never returned in responses).'),
        private: zod
            .boolean()
            .default(sandboxCreateBodyPrivateDefault)
            .describe('If true, only the creator can see this environment; otherwise the whole team can.'),
        custom_image_id: zod
            .uuid()
            .nullish()
            .describe(
                "Custom base image for this environment's sandboxes (Modal VM runtime only); null uses the default base."
            ),
    })
    .describe('Request body for creating or updating a sandbox environment.')

/**
 * API for managing sandbox environments that control network access for task runs.
 */
export const sandboxPartialUpdateBodyNameMax = 255

export const sandboxPartialUpdateBodyNetworkAccessLevelDefault = `full`
export const sandboxPartialUpdateBodyAllowedDomainsItemMax = 255

export const sandboxPartialUpdateBodyAllowedDomainsMax = 100

export const sandboxPartialUpdateBodyIncludeDefaultDomainsDefault = false
export const sandboxPartialUpdateBodyRepositoriesItemMax = 255

export const sandboxPartialUpdateBodyPrivateDefault = true

export const SandboxPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(sandboxPartialUpdateBodyNameMax)
            .optional()
            .describe('Display name for the environment.'),
        network_access_level: zod
            .enum(['trusted', 'full', 'custom'])
            .describe('\* `trusted` - Trusted\n\* `full` - Full\n\* `custom` - Custom')
            .default(sandboxPartialUpdateBodyNetworkAccessLevelDefault)
            .describe(
                'Network access policy: trusted (default allowlist), full (unrestricted), or custom.\n\n\* `trusted` - Trusted\n\* `full` - Full\n\* `custom` - Custom'
            ),
        allowed_domains: zod
            .array(zod.string().max(sandboxPartialUpdateBodyAllowedDomainsItemMax))
            .max(sandboxPartialUpdateBodyAllowedDomainsMax)
            .optional()
            .describe('Allowed domains for custom network access.'),
        include_default_domains: zod
            .boolean()
            .default(sandboxPartialUpdateBodyIncludeDefaultDomainsDefault)
            .describe('Whether to include default trusted domains (GitHub, npm, PyPI).'),
        repositories: zod
            .array(zod.string().max(sandboxPartialUpdateBodyRepositoriesItemMax))
            .optional()
            .describe('Repositories this environment applies to (format: org\/repo).'),
        environment_variables: zod
            .unknown()
            .optional()
            .describe('Encrypted environment variables (write-only, never returned in responses).'),
        private: zod
            .boolean()
            .default(sandboxPartialUpdateBodyPrivateDefault)
            .describe('If true, only the creator can see this environment; otherwise the whole team can.'),
        custom_image_id: zod
            .uuid()
            .nullish()
            .describe(
                "Custom base image for this environment's sandboxes (Modal VM runtime only); null uses the default base."
            ),
    })
    .describe('Request body for creating or updating a sandbox environment.')

/**
 * Clear collapsed task activity through task timestamps and individual comment activity through activity IDs.
 * @summary Mark task activity read
 */
export const taskActivityMarkReadCreateBodyActivitiesMax = 500

export const TaskActivityMarkReadCreateBody = /* @__PURE__ */ zod
    .object({
        activities: zod
            .array(
                zod.object({
                    task_id: zod.uuid().describe('Task whose displayed activity should be marked read.'),
                    activity_id: zod
                        .uuid()
                        .nullish()
                        .describe('Comment activity row to mark read. Omit for collapsed task activity.'),
                    seen_before: zod.iso
                        .datetime({ offset: true })
                        .describe('Mark activity at or before this timestamp read without clearing newer activity.'),
                })
            )
            .max(taskActivityMarkReadCreateBodyActivitiesMax)
            .describe('Displayed task activities to mark read if they have not changed.'),
    })
    .describe('Request body for clearing the unread flag on specific tasks.')

/**
 * Returns the existing public channel with the (normalized) name, creating it if needed. A channel created here is starred for the requester unless star is false. The general name returns the team's general space; names that read as a private space ("me", "personal") are rejected.
 * @summary Resolve or create a public channel
 */
export const taskChannelsCreateBodyNameMax = 128

export const taskChannelsCreateBodyStarDefault = true

export const TaskChannelsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(taskChannelsCreateBodyNameMax)
            .describe('Channel name, rendered as #<name>. Normalized to lowercase-dashed.'),
        star: zod
            .boolean()
            .default(taskChannelsCreateBodyStarDefault)
            .describe(
                'Star the channel for the requester when this call creates it. Ignored when the channel already exists, which leaves existing stars untouched.'
            ),
    })
    .describe('Request body for creating (resolve-or-create) or renaming a public channel.')

/**
 * API for a channel's system-announcement feed — durable "PostHog agent" rows
 * (context created, CONTEXT.md being built) rendered alongside the channel's task
 * cards. Read by any team member for a public channel; personal channels are owner-only.
 * @summary Post a channel feed message
 */
export const TaskChannelsFeedCreateBody = /* @__PURE__ */ zod
    .object({
        event: zod
            .enum(['context_created', 'context_md_building'])
            .describe('\* `context_created` - context_created\n\* `context_md_building` - context_md_building')
            .describe(
                'Lifecycle event key.\n\n\* `context_created` - context_created\n\* `context_md_building` - context_md_building'
            ),
        payload: zod
            .unknown()
            .optional()
            .describe('Structured event data, e.g. {\"context_name\": \"mobile\"}. At most 8 KB of JSON.'),
        created_at: zod.iso
            .datetime({ offset: true })
            .optional()
            .describe(
                'Optional explicit timestamp (within 10 minutes of now), so a client can order a burst of announcements.'
            ),
    })
    .describe("Request body for posting a system announcement into a channel's feed.")

/**
 * API for task channels — the shared feeds tasks are kicked off in. The
 * provision_defaults action get-or-creates the requester's personal "#me" channel and
 * the team's shared "#general" channel; creation is resolve-or-create by normalized
 * name so clients can map channel-like surfaces onto backend channels.
 * @summary Rename a public channel
 */
export const taskChannelsPartialUpdateBodyNameMax = 128

export const taskChannelsPartialUpdateBodyRepositoriesItemMax = 255

export const taskChannelsPartialUpdateBodyRepositoriesMax = 10

export const TaskChannelsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(taskChannelsPartialUpdateBodyNameMax)
        .optional()
        .describe('Channel name, rendered as #<name>. Normalized to lowercase-dashed.'),
    github_integration: zod
        .number()
        .nullish()
        .describe('Team GitHub integration used for repositories linked to this channel.'),
    repositories: zod
        .array(zod.string().max(taskChannelsPartialUpdateBodyRepositoriesItemMax))
        .max(taskChannelsPartialUpdateBodyRepositoriesMax)
        .optional()
        .describe('GitHub repositories inherited by new tasks in this channel.'),
})

/**
 * API for task channels — the shared feeds tasks are kicked off in. The
 * provision_defaults action get-or-creates the requester's personal "#me" channel and
 * the team's shared "#general" channel; creation is resolve-or-create by normalized
 * name so clients can map channel-like surfaces onto backend channels.
 * @summary Set or clear the channel's CONTEXT.md generation task
 */
export const TaskChannelsContextGenerationUpdateBody = /* @__PURE__ */ zod
    .object({
        task_id: zod.uuid().nullable(),
    })
    .describe("The task currently generating this channel's CONTEXT.md, or null.")

/**
 * Publish a new version of the channel's CONTEXT.md instructions. Pass base_version (the version you read) so a concurrent edit is rejected with 409 instead of overwritten.
 * @summary Publish channel instructions
 */
export const taskChannelsInstructionsUpdateBodyContentMax = 100000

export const taskChannelsInstructionsUpdateBodyBaseVersionMin = 0

export const TaskChannelsInstructionsUpdateBody = /* @__PURE__ */ zod
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
 * Publish a new version of the channel's CONTEXT.md instructions. Pass base_version (the version you read) so a concurrent edit is rejected with 409 instead of overwritten.
 * @summary Publish channel instructions
 */
export const taskChannelsInstructionsPartialUpdateBodyContentMax = 100000

export const taskChannelsInstructionsPartialUpdateBodyBaseVersionMin = 0

export const TaskChannelsInstructionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        content: zod
            .string()
            .max(taskChannelsInstructionsPartialUpdateBodyContentMax)
            .optional()
            .describe('The complete markdown instructions (CONTEXT.md) for the channel.'),
        base_version: zod
            .number()
            .min(taskChannelsInstructionsPartialUpdateBodyBaseVersionMin)
            .nullish()
            .describe(
                'Optimistic-concurrency guard: the version the edit is based on (0 for a channel with no instructions yet). A stale base is rejected with 409; omit to publish unguarded.'
            ),
    })
    .describe('Request body for publishing a new instructions version.')

/**
 * API for task channels — the shared feeds tasks are kicked off in. The
 * provision_defaults action get-or-creates the requester's personal "#me" channel and
 * the team's shared "#general" channel; creation is resolve-or-create by normalized
 * name so clients can map channel-like surfaces onto backend channels.
 * @summary Star or unstar a channel for the requesting user
 */
export const TaskChannelsStarCreateBody = /* @__PURE__ */ zod
    .object({
        starred: zod.boolean(),
    })
    .describe('Request body for starring\/unstarring a channel for the requesting user.')

/**
 * Feature-flagged test path that creates a repeatable session from explicit prompt-building inputs, in the requester's personal space.
 * @summary Start a test first-run onboarding session
 */
export const taskChannelsOnboardingSessionTestCreateBodyCompanyDomainDefault = ``
export const taskChannelsOnboardingSessionTestCreateBodyCompanyDomainMax = 253

export const taskChannelsOnboardingSessionTestCreateBodyJoiningExistingOrganizationDefault = false
export const taskChannelsOnboardingSessionTestCreateBodyHasEventsDefault = false
export const taskChannelsOnboardingSessionTestCreateBodySignalReportsWaitingDefault = 0
export const taskChannelsOnboardingSessionTestCreateBodySignalReportsWaitingMin = 0
export const taskChannelsOnboardingSessionTestCreateBodySignalReportsWaitingMax = 10000

export const taskChannelsOnboardingSessionTestCreateBodyOtherMembersItemMax = 100

export const taskChannelsOnboardingSessionTestCreateBodyOtherMembersMax = 25

export const taskChannelsOnboardingSessionTestCreateBodySourcesEnabledItemMax = 100

export const taskChannelsOnboardingSessionTestCreateBodySourcesEnabledMax = 25

export const taskChannelsOnboardingSessionTestCreateBodySourcesWatchingItemMax = 100

export const taskChannelsOnboardingSessionTestCreateBodySourcesWatchingMax = 25

export const taskChannelsOnboardingSessionTestCreateBodySourcesNewlyEnabledDefault = false

export const TaskChannelsOnboardingSessionTestCreateBody = /* @__PURE__ */ zod.object({
    company_domain: zod
        .string()
        .max(taskChannelsOnboardingSessionTestCreateBodyCompanyDomainMax)
        .default(taskChannelsOnboardingSessionTestCreateBodyCompanyDomainDefault)
        .describe('Company domain to research. Blank simulates a personal email address.'),
    joining_existing_organization: zod
        .boolean()
        .default(taskChannelsOnboardingSessionTestCreateBodyJoiningExistingOrganizationDefault)
        .describe('Whether the user is joining an organization that already has shared context.'),
    has_events: zod
        .boolean()
        .default(taskChannelsOnboardingSessionTestCreateBodyHasEventsDefault)
        .describe('Whether the project has ingested events.'),
    signal_reports_waiting: zod
        .number()
        .min(taskChannelsOnboardingSessionTestCreateBodySignalReportsWaitingMin)
        .max(taskChannelsOnboardingSessionTestCreateBodySignalReportsWaitingMax)
        .default(taskChannelsOnboardingSessionTestCreateBodySignalReportsWaitingDefault)
        .describe('Number of findings waiting in #general.'),
    other_members: zod
        .array(zod.string().max(taskChannelsOnboardingSessionTestCreateBodyOtherMembersItemMax))
        .max(taskChannelsOnboardingSessionTestCreateBodyOtherMembersMax)
        .optional()
        .describe('Display names of other Desktop users in the organization.'),
    sources_enabled: zod
        .array(zod.string().max(taskChannelsOnboardingSessionTestCreateBodySourcesEnabledItemMax))
        .max(taskChannelsOnboardingSessionTestCreateBodySourcesEnabledMax)
        .optional()
        .describe('Signal sources that were already enabled.'),
    sources_watching: zod
        .array(zod.string().max(taskChannelsOnboardingSessionTestCreateBodySourcesWatchingItemMax))
        .max(taskChannelsOnboardingSessionTestCreateBodySourcesWatchingMax)
        .optional()
        .describe('Signal sources the onboarding flow is watching.'),
    sources_newly_enabled: zod
        .boolean()
        .default(taskChannelsOnboardingSessionTestCreateBodySourcesNewlyEnabledDefault)
        .describe('Whether onboarding enabled any signal sources.'),
})

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const tasksCreateBodyTitleMax = 255

export const tasksCreateBodyRepositoryMax = 255

export const tasksCreateBodyRepositoriesItemMax = 255

export const tasksCreateBodyRepositoriesMax = 10

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
                'loop',
                'mcp_analytics',
                'signals_chat',
                'task_analysis',
                'workflow',
            ])
            .describe(
                '\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics\n\* `signals_chat` - Signals Chat\n\* `task_analysis` - Task Analysis\n\* `workflow` - Workflow'
            )
            .optional()
            .describe(
                'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.\n\n\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics\n\* `signals_chat` - Signals Chat\n\* `task_analysis` - Task Analysis\n\* `workflow` - Workflow'
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
            .uuid()
            .nullish()
            .describe('User-scoped GitHub integration to use for user-authored cloud runs.'),
        signal_report: zod.uuid().nullish().describe('Signal report this task implements, when created from a report.'),
        signal_report_task_relationship: zod
            .string()
            .max(tasksCreateBodySignalReportTaskRelationshipMax)
            .optional()
            .describe(
                "How the created task relates to the signal report (e.g. 'implementation', 'discussion'). Recorded as a signals task_run work-log entry; 'implementation' also opens the auto-start spend gate. Any routing-safe identifier (lowercase letters, numbers, '_', '-') is accepted except labels reserved for server-created tasks ('research', 'repo_selection', 'scout'). Non-implementation labels count toward the report's discussion task limit."
            ),
        json_schema: zod.unknown().optional().describe('JSON schema used to validate the output of the task.'),
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
            .union([zod.enum(['claude', 'codex']).describe('\* `claude` - claude\n\* `codex` - codex'), zod.null()])
            .optional()
            .describe(
                "Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: used only to reuse a pre-warmed Run started on the same runtime. A value differing from the warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime.\n\n\* `claude` - claude\n\* `codex` - codex"
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
                    .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                    .describe(
                        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
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
                'Selected agent permission mode. Write-only; used only to reuse a warm Run booted on the same mode. Omit to reuse a warm Run whatever mode it booted on.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access'
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
        channel: zod.uuid().nullish().describe('Channel this task is owned by (the channel it was kicked off in).'),
        naming_source: zod
            .string()
            .optional()
            .describe(
                'Text the server generates the title from instead of `description`. Lets a client whose `description` is only an attachment summary (e.g. pasted text stored as a file) supply the real content for naming, so `description` (the prompt passed to the agent) stays unchanged. Not persisted.'
            ),
        sandbox_environment_id: zod
            .uuid()
            .nullish()
            .describe('Sandbox environment selected for matching a pre-warmed cloud run. Not persisted on the task.'),
        custom_image_id: zod
            .uuid()
            .nullish()
            .describe('Custom image selected for matching a pre-warmed cloud run. Not persisted on the task.'),
        runtime: zod
            .enum(['acp', 'pi'])
            .describe('\* `acp` - ACP\n\* `pi` - Pi')
            .optional()
            .describe(
                "Agent protocol and harness used for this task's runs. Defaults to ACP when omitted.\n\n\* `acp` - ACP\n\* `pi` - Pi"
            ),
    })
    .describe(
        'Request body for creating or updating a task.\n\nField required\/default semantics match the ``Task`` model. The view passes\n``validated_data`` (integration\/report PK fields already resolved to instances) to the\nfacade ``create_task`` \/ ``update_task`` functions.'
    )

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const tasksUpdateBodyTitleMax = 255

export const tasksUpdateBodyRepositoryMax = 255

export const tasksUpdateBodyRepositoriesItemMax = 255

export const tasksUpdateBodyRepositoriesMax = 10

export const tasksUpdateBodySignalReportTaskRelationshipMax = 200

export const tasksUpdateBodyBranchMax = 255

export const tasksUpdateBodyPendingUserArtifactIdsItemMax = 128

export const TasksUpdateBody = /* @__PURE__ */ zod
    .object({
        title: zod
            .string()
            .max(tasksUpdateBodyTitleMax)
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
                '\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics\n\* `signals_chat` - Signals Chat\n\* `task_analysis` - Task Analysis\n\* `workflow` - Workflow'
            )
            .optional()
            .describe(
                'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.\n\n\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics\n\* `signals_chat` - Signals Chat\n\* `task_analysis` - Task Analysis\n\* `workflow` - Workflow'
            ),
        repository: zod
            .string()
            .max(tasksUpdateBodyRepositoryMax)
            .nullish()
            .describe('Target GitHub repository in `organization\/repo` format (e.g. `posthog\/posthog-js`).'),
        repositories: zod
            .array(zod.string().max(tasksUpdateBodyRepositoriesItemMax))
            .max(tasksUpdateBodyRepositoriesMax)
            .optional()
            .describe('GitHub repositories available to this task, each in `organization\/repo` format.'),
        github_integration: zod.number().nullish().describe('GitHub integration for this task.'),
        github_user_integration: zod
            .uuid()
            .nullish()
            .describe('User-scoped GitHub integration to use for user-authored cloud runs.'),
        signal_report: zod.uuid().nullish().describe('Signal report this task implements, when created from a report.'),
        signal_report_task_relationship: zod
            .string()
            .max(tasksUpdateBodySignalReportTaskRelationshipMax)
            .optional()
            .describe(
                "How the created task relates to the signal report (e.g. 'implementation', 'discussion'). Recorded as a signals task_run work-log entry; 'implementation' also opens the auto-start spend gate. Any routing-safe identifier (lowercase letters, numbers, '_', '-') is accepted except labels reserved for server-created tasks ('research', 'repo_selection', 'scout'). Non-implementation labels count toward the report's discussion task limit."
            ),
        json_schema: zod.unknown().optional().describe('JSON schema used to validate the output of the task.'),
        archived: zod.boolean().optional().describe('If true, the task is hidden from default list responses.'),
        ci_prompt: zod
            .string()
            .nullish()
            .describe('Custom prompt for CI fixes. If blank, a default prompt will be used.'),
        branch: zod
            .string()
            .max(tasksUpdateBodyBranchMax)
            .nullish()
            .describe(
                'Branch the user has selected for this cloud task. Write-only and not persisted on the task itself: used only to reuse a matching pre-warmed sandbox Run on creation (the branch is otherwise carried on the run). Omit to match a warm Run on the default branch.'
            ),
        runtime_adapter: zod
            .union([zod.enum(['claude', 'codex']).describe('\* `claude` - claude\n\* `codex` - codex'), zod.null()])
            .optional()
            .describe(
                "Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: used only to reuse a pre-warmed Run started on the same runtime. A value differing from the warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime.\n\n\* `claude` - claude\n\* `codex` - codex"
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
                    .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                    .describe(
                        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
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
                'Selected agent permission mode. Write-only; used only to reuse a warm Run booted on the same mode. Omit to reuse a warm Run whatever mode it booted on.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access'
            ),
        pending_user_message: zod
            .string()
            .nullish()
            .describe(
                'First user message to forward when creation reuses a pre-warmed Run. Write-only and not persisted on the task: lets clients deliver a message that differs from `description` (e.g. a resolved skill invocation with channel context folded in). Ignored when no warm Run is reused — cold creation takes the first message via the run start endpoint instead.'
            ),
        pending_user_artifact_ids: zod
            .array(zod.string().max(tasksUpdateBodyPendingUserArtifactIdsItemMax))
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
        channel: zod.uuid().nullish().describe('Channel this task is owned by (the channel it was kicked off in).'),
    })
    .describe(
        'Request body for creating or updating a task.\n\nField required\/default semantics match the ``Task`` model. The view passes\n``validated_data`` (integration\/report PK fields already resolved to instances) to the\nfacade ``create_task`` \/ ``update_task`` functions.'
    )

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const tasksPartialUpdateBodyTitleMax = 255

export const tasksPartialUpdateBodyRepositoryMax = 255

export const tasksPartialUpdateBodyRepositoriesItemMax = 255

export const tasksPartialUpdateBodyRepositoriesMax = 10

export const tasksPartialUpdateBodySignalReportTaskRelationshipMax = 200

export const tasksPartialUpdateBodyBranchMax = 255

export const tasksPartialUpdateBodyPendingUserArtifactIdsItemMax = 128

export const TasksPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        title: zod
            .string()
            .max(tasksPartialUpdateBodyTitleMax)
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
                '\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics\n\* `signals_chat` - Signals Chat\n\* `task_analysis` - Task Analysis\n\* `workflow` - Workflow'
            )
            .optional()
            .describe(
                'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.\n\n\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics\n\* `signals_chat` - Signals Chat\n\* `task_analysis` - Task Analysis\n\* `workflow` - Workflow'
            ),
        repository: zod
            .string()
            .max(tasksPartialUpdateBodyRepositoryMax)
            .nullish()
            .describe('Target GitHub repository in `organization\/repo` format (e.g. `posthog\/posthog-js`).'),
        repositories: zod
            .array(zod.string().max(tasksPartialUpdateBodyRepositoriesItemMax))
            .max(tasksPartialUpdateBodyRepositoriesMax)
            .optional()
            .describe('GitHub repositories available to this task, each in `organization\/repo` format.'),
        github_integration: zod.number().nullish().describe('GitHub integration for this task.'),
        github_user_integration: zod
            .uuid()
            .nullish()
            .describe('User-scoped GitHub integration to use for user-authored cloud runs.'),
        signal_report: zod.uuid().nullish().describe('Signal report this task implements, when created from a report.'),
        signal_report_task_relationship: zod
            .string()
            .max(tasksPartialUpdateBodySignalReportTaskRelationshipMax)
            .optional()
            .describe(
                "How the created task relates to the signal report (e.g. 'implementation', 'discussion'). Recorded as a signals task_run work-log entry; 'implementation' also opens the auto-start spend gate. Any routing-safe identifier (lowercase letters, numbers, '_', '-') is accepted except labels reserved for server-created tasks ('research', 'repo_selection', 'scout'). Non-implementation labels count toward the report's discussion task limit."
            ),
        json_schema: zod.unknown().optional().describe('JSON schema used to validate the output of the task.'),
        archived: zod.boolean().optional().describe('If true, the task is hidden from default list responses.'),
        ci_prompt: zod
            .string()
            .nullish()
            .describe('Custom prompt for CI fixes. If blank, a default prompt will be used.'),
        branch: zod
            .string()
            .max(tasksPartialUpdateBodyBranchMax)
            .nullish()
            .describe(
                'Branch the user has selected for this cloud task. Write-only and not persisted on the task itself: used only to reuse a matching pre-warmed sandbox Run on creation (the branch is otherwise carried on the run). Omit to match a warm Run on the default branch.'
            ),
        runtime_adapter: zod
            .union([zod.enum(['claude', 'codex']).describe('\* `claude` - claude\n\* `codex` - codex'), zod.null()])
            .optional()
            .describe(
                "Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: used only to reuse a pre-warmed Run started on the same runtime. A value differing from the warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime.\n\n\* `claude` - claude\n\* `codex` - codex"
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
                    .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                    .describe(
                        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
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
                'Selected agent permission mode. Write-only; used only to reuse a warm Run booted on the same mode. Omit to reuse a warm Run whatever mode it booted on.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access'
            ),
        pending_user_message: zod
            .string()
            .nullish()
            .describe(
                'First user message to forward when creation reuses a pre-warmed Run. Write-only and not persisted on the task: lets clients deliver a message that differs from `description` (e.g. a resolved skill invocation with channel context folded in). Ignored when no warm Run is reused — cold creation takes the first message via the run start endpoint instead.'
            ),
        pending_user_artifact_ids: zod
            .array(zod.string().max(tasksPartialUpdateBodyPendingUserArtifactIdsItemMax))
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
        channel: zod.uuid().nullish().describe('Channel this task is owned by (the channel it was kicked off in).'),
    })
    .describe(
        'Request body for creating or updating a task.\n\nField required\/default semantics match the ``Task`` model. The view passes\n``validated_data`` (integration\/report PK fields already resolved to instances) to the\nfacade ``create_task`` \/ ``update_task`` functions.'
    )

/**
 * Transfer ownership of a task to another member of the project: they take over driving it (steering, archiving, running), and future runs resolve GitHub authorship and notification recipients from them. Only the task's current owner can hand it off. Every run must be finished or canceled, and every sandbox must be shut down first. A task in a private space moves into the recipient's private space; a task in a shared space stays there.
 * @summary Hand a task off to a colleague
 */

export const TasksHandoffCreateBody = /* @__PURE__ */ zod
    .object({
        user: zod
            .number()
            .min(1)
            .describe(
                "ID of the user taking over the task. Must have access to this project and not be the task's current owner."
            ),
    })
    .describe('Request body for handing a task off to a colleague: they become its owner.')

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksPinCreateBody = /* @__PURE__ */ zod.object({
    pinned: zod.boolean().describe('Whether the task should be pinned for the requester.'),
})

/**
 * Idempotent upsert: marks the calling user + `device_id` as actively watching this task for the next ~60 seconds. While at least one device for the user has a non-expired presence row for this task, the push fanout will skip ALL of that user's other registered devices for task notifications — the contract is 'if any device is demonstrably watching, suppress the others'. Clients call this every ~30s while the task screen is foregrounded. `device_id` is the UUID of the caller's UserPushToken row.
 * @summary Beacon presence for a device watching this task
 */
export const TasksPresenceCreateBody = /* @__PURE__ */ zod
    .object({
        device_id: zod
            .uuid()
            .describe(
                "UUID of the caller's UserPushToken (returned by `\/api\/users\/@me\/push_tokens\/` on register)."
            ),
    })
    .describe(
        "Request body for the presence beacon and beacon-leave endpoints.\n\n`device_id` is the UUID of the caller's `UserPushToken` row, which the\nclient received when it registered for push via `\/api\/users\/@me\/push_tokens\/`.\nThe client is expected to use the same identifier on the beacon and leave\ncalls; if the user has unregistered the underlying push token, the value\nwon't resolve and the call returns 404 — at which point pushes were\nalready not going there anyway."
    )

/**
 * Create a new task run and kick off the workflow.
 * @summary Run task
 */
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

export const TasksRunCreateBody = /* @__PURE__ */ zod.union([
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
            custom_image_id: zod
                .uuid()
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
                .enum(['manual', 'signal_report'])
                .describe('\* `manual` - manual\n\* `signal_report` - signal_report')
                .optional()
                .describe(
                    'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n\* `manual` - manual\n\* `signal_report` - signal_report'
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
            rtk_enabled: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether rtk command-output compression is enabled for this run. Omitted or null follows the server-side default (enabled); false opts this run out.'
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
            custom_image_id: zod
                .uuid()
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
                .enum(['manual', 'signal_report'])
                .describe('\* `manual` - manual\n\* `signal_report` - signal_report')
                .optional()
                .describe(
                    'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n\* `manual` - manual\n\* `signal_report` - signal_report'
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
            rtk_enabled: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether rtk command-output compression is enabled for this run. Omitted or null follows the server-side default (enabled); false opts this run out.'
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
        custom_image_id: zod
            .uuid()
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
            .enum(['manual', 'signal_report'])
            .describe('\* `manual` - manual\n\* `signal_report` - signal_report')
            .optional()
            .describe(
                'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n\* `manual` - manual\n\* `signal_report` - signal_report'
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
 * Verify staged S3 uploads and cache their metadata so they can be attached to the next run created for this task.
 * @summary Finalize staged direct uploads for task attachments
 */
export const tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemNameMax = 255

export const tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemSourceDefault = ``
export const tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemSourceMax = 64

export const tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemStoragePathMax = 500

export const tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemContentTypeMax = 255

export const tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemMetadataOneSkillNameMax = 255

export const tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemMetadataOneContentSha256RegExp = new RegExp(
    '^[a-f0-9]{64}$'
)

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
                    .enum([
                        'plan',
                        'context',
                        'reference',
                        'output',
                        'artifact',
                        'tree_snapshot',
                        'user_attachment',
                        'skill_bundle',
                    ])
                    .describe(
                        '\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
                    )
                    .describe(
                        'Classification for the artifact\n\n\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
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
                metadata: zod
                    .object({
                        skill_name: zod
                            .string()
                            .max(tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemMetadataOneSkillNameMax)
                            .describe('Name of the local skill included in a skill_bundle artifact.'),
                        skill_source: zod
                            .enum(['user', 'repo', 'marketplace', 'codex'])
                            .describe(
                                '\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
                            )
                            .describe(
                                'Local source for the uploaded skill bundle, such as user or repo.\n\n\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
                            ),
                        content_sha256: zod
                            .string()
                            .regex(
                                tasksStagedArtifactsFinalizeUploadCreateBodyArtifactsItemMetadataOneContentSha256RegExp
                            )
                            .describe('SHA-256 hex digest of the uploaded skill bundle bytes.'),
                        bundle_format: zod
                            .enum(['zip'])
                            .describe('\* `zip` - zip')
                            .describe('Archive format used for the local skill bundle.\n\n\* `zip` - zip'),
                        schema_version: zod
                            .number()
                            .min(1)
                            .describe('Version of the local skill bundle metadata schema.'),
                    })
                    .optional()
                    .describe('Skill bundle metadata, required when the artifact type is skill_bundle.'),
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

export const tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemMetadataOneSkillNameMax = 255

export const tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemMetadataOneContentSha256RegExp = new RegExp(
    '^[a-f0-9]{64}$'
)

export const TasksStagedArtifactsPrepareUploadCreateBody = /* @__PURE__ */ zod.object({
    artifacts: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .max(tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemNameMax)
                    .describe('File name to associate with the staged artifact'),
                type: zod
                    .enum([
                        'plan',
                        'context',
                        'reference',
                        'output',
                        'artifact',
                        'tree_snapshot',
                        'user_attachment',
                        'skill_bundle',
                    ])
                    .describe(
                        '\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
                    )
                    .describe(
                        'Classification for the artifact\n\n\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
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
                metadata: zod
                    .object({
                        skill_name: zod
                            .string()
                            .max(tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemMetadataOneSkillNameMax)
                            .describe('Name of the local skill included in a skill_bundle artifact.'),
                        skill_source: zod
                            .enum(['user', 'repo', 'marketplace', 'codex'])
                            .describe(
                                '\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
                            )
                            .describe(
                                'Local source for the uploaded skill bundle, such as user or repo.\n\n\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
                            ),
                        content_sha256: zod
                            .string()
                            .regex(
                                tasksStagedArtifactsPrepareUploadCreateBodyArtifactsItemMetadataOneContentSha256RegExp
                            )
                            .describe('SHA-256 hex digest of the uploaded skill bundle bytes.'),
                        bundle_format: zod
                            .enum(['zip'])
                            .describe('\* `zip` - zip')
                            .describe('Archive format used for the local skill bundle.\n\n\* `zip` - zip'),
                        schema_version: zod
                            .number()
                            .min(1)
                            .describe('Version of the local skill bundle metadata schema.'),
                    })
                    .optional()
                    .describe('Skill bundle metadata, required when the artifact type is skill_bundle.'),
            })
        )
        .describe('Array of staged artifacts to prepare before creating a run'),
})

/**
 * Warm an idling successor for the task's latest terminal Run while the user composes the next message. The successor restores the prior snapshot when compatible and waits for the normal run endpoint to activate it. Best-effort: returns an empty body when warming is disabled, capped, or the task advanced to another Run.
 * @summary Warm a resumed task sandbox
 */
export const TasksWarmResumeCreateBody = /* @__PURE__ */ zod
    .object({
        resume_from_run_id: zod
            .uuid()
            .describe("ID of the task's latest terminal run whose snapshot and conversation should be resumed."),
        runtime_adapter: zod
            .enum(['claude', 'codex'])
            .describe('\* `claude` - claude\n\* `codex` - codex')
            .optional()
            .describe(
                'Agent runtime adapter to start before the next message is submitted.\n\n\* `claude` - claude\n\* `codex` - codex'
            ),
        model: zod.string().optional().describe('LLM model to start before the next message is submitted.'),
        reasoning_effort: zod
            .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
            .describe(
                '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
            )
            .optional()
            .describe(
                'Reasoning effort to apply when the warmed successor receives its first message.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
            ),
        initial_permission_mode: zod
            .enum(['default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto', 'read-only', 'full-access'])
            .describe(
                '\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access'
            )
            .optional()
            .describe(
                "Initial permission mode for the warmed successor's agent session.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access"
            ),
    })
    .describe('Request body for warming a successor to an existing terminal task run.')

/**
 * Create a new run for a specific task without starting execution.
 * @summary Create task run
 */
export const tasksRunsCreateBodyImportedMcpServersItemNameMax = 64

export const tasksRunsCreateBodyImportedMcpServersItemUrlMax = 2048

export const tasksRunsCreateBodyImportedMcpServersItemHeadersItemNameMax = 256

export const tasksRunsCreateBodyImportedMcpServersItemHeadersItemValueMax = 4096

export const tasksRunsCreateBodyRelayedMcpServersItemNameMax = 64

export const tasksRunsCreateBodyEnvironmentDefault = `local`
export const tasksRunsCreateBodyModeDefault = `background`
export const tasksRunsCreateBodyBranchMax = 255

export const TasksRunsCreateBody = /* @__PURE__ */ zod
    .object({
        imported_mcp_servers: zod
            .array(
                zod
                    .object({
                        type: zod.enum(['http', 'sse']).describe('\* `http` - http\n\* `sse` - sse'),
                        name: zod.string().max(tasksRunsCreateBodyImportedMcpServersItemNameMax),
                        url: zod.url().max(tasksRunsCreateBodyImportedMcpServersItemUrlMax),
                        headers: zod
                            .array(
                                zod.object({
                                    name: zod.string().max(tasksRunsCreateBodyImportedMcpServersItemHeadersItemNameMax),
                                    value: zod
                                        .string()
                                        .max(tasksRunsCreateBodyImportedMcpServersItemHeadersItemValueMax),
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
                        name: zod.string().max(tasksRunsCreateBodyRelayedMcpServersItemNameMax),
                    })
                    .describe('One desktop-only MCP server relayed into the run — a name only, never configuration.')
            )
            .nullish()
            .describe(
                'Names of desktop-only MCP servers the creating client (PostHog Desktop) relays into the cloud sandbox over the durable event\/command channel. Names only — the server configuration (command, env, URL, headers) never crosses the wire.'
            ),
        environment: zod
            .enum(['local', 'cloud'])
            .describe('\* `local` - local\n\* `cloud` - cloud')
            .default(tasksRunsCreateBodyEnvironmentDefault)
            .describe(
                "Execution environment for the new run. Use 'cloud' for remote sandbox runs and 'local' for desktop sessions.\n\n\* `local` - local\n\* `cloud` - cloud"
            ),
        mode: zod
            .enum(['interactive', 'background'])
            .describe('\* `interactive` - interactive\n\* `background` - background')
            .default(tasksRunsCreateBodyModeDefault)
            .describe(
                "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n\* `interactive` - interactive\n\* `background` - background"
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
        custom_image_id: zod
            .uuid()
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
            .enum(['manual', 'signal_report'])
            .describe('\* `manual` - manual\n\* `signal_report` - signal_report')
            .optional()
            .describe(
                'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n\* `manual` - manual\n\* `signal_report` - signal_report'
            ),
        signal_report_id: zod
            .string()
            .optional()
            .describe('Optional signal report identifier when this run was started from Inbox.'),
        runtime_adapter: zod
            .enum(['claude', 'codex'])
            .describe('\* `claude` - claude\n\* `codex` - codex')
            .optional()
            .describe(
                "Agent runtime adapter to launch for this run. Use 'claude' for the Claude runtime or 'codex' for the Codex runtime.\n\n\* `claude` - claude\n\* `codex` - codex"
            ),
        model: zod.string().optional().describe('LLM model identifier to run in the selected runtime.'),
        reasoning_effort: zod
            .enum(['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
            .describe(
                '\* `off` - off\n\* `minimal` - minimal\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
            )
            .optional()
            .describe(
                'Reasoning effort to request for models that expose an effort control.\n\n\* `off` - off\n\* `minimal` - minimal\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
            ),
        context_window: zod
            .enum(['200k', '1m'])
            .describe('\* `200k` - 200k\n\* `1m` - 1m')
            .optional()
            .describe('Context window size for models that support the 1M window.\n\n\* `200k` - 200k\n\* `1m` - 1m'),
        fast_mode: zod.boolean().nullish().describe('Enable fast mode for models that support it.'),
        github_user_token: zod
            .string()
            .optional()
            .describe('Ephemeral GitHub user token from PostHog Desktop for user-authored cloud pull requests.'),
        initial_permission_mode: zod
            .enum(['default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto', 'read-only', 'full-access'])
            .describe(
                '\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access'
            )
            .optional()
            .describe(
                "Initial permission mode for the agent session. Claude runtimes accept PostHog permission presets like 'plan'. Codex runtimes accept native Codex modes like 'plan', 'auto', and 'read-only'.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access"
            ),
        rtk_enabled: zod
            .boolean()
            .nullish()
            .describe(
                'Whether rtk command-output compression is enabled for this run. Omitted or null follows the server-side default (enabled); false opts this run out.'
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
            '\* `not_started` - not_started\n\* `queued` - queued\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `cancelled` - cancelled'
        )
        .optional()
        .describe(
            'Current execution status\n\n\* `not_started` - not_started\n\* `queued` - queued\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `cancelled` - cancelled'
        ),
    branch: zod.string().nullish().describe('Git branch name to associate with the task'),
    stage: zod.string().nullish().describe('Current stage of the run (e.g. research, plan, build)'),
    output: zod.unknown().optional().describe('Output from the run'),
    state: zod.unknown().optional().describe('State of the run'),
    state_remove_keys: zod
        .array(zod.string())
        .optional()
        .describe('State keys to remove atomically before applying any state updates.'),
    state_append: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'State keys whose value to append to the list stored at that key, atomically under the row lock. Use instead of sending the whole list back through `state`, which loses concurrent appends to a read-modify-write race.'
        ),
    error_message: zod.string().nullish().describe('Error message if execution failed'),
})

/**
 * Store one verified inefficiency finding on a task-analysis run. Only the run's own task-bound sandbox agent may call it, and only on a task-analysis run. The findings list is server-owned: it is not writable through the run update endpoint.
 * @summary Report an analysis finding
 */
export const tasksRunsAnalysisInsightCreateBodyObservationMin = 80
export const tasksRunsAnalysisInsightCreateBodyObservationMax = 500

export const tasksRunsAnalysisInsightCreateBodyEvidenceItemQuoteMin = 20
export const tasksRunsAnalysisInsightCreateBodyEvidenceItemQuoteMax = 300

export const tasksRunsAnalysisInsightCreateBodyOtherJustificationMin = 50
export const tasksRunsAnalysisInsightCreateBodyOtherJustificationMax = 200

export const tasksRunsAnalysisInsightCreateBodySuggestedFixOneChangeMin = 50
export const tasksRunsAnalysisInsightCreateBodySuggestedFixOneChangeMax = 400

export const tasksRunsAnalysisInsightCreateBodySuggestedFixOneDoneWhenMin = 30
export const tasksRunsAnalysisInsightCreateBodySuggestedFixOneDoneWhenMax = 200

export const tasksRunsAnalysisInsightCreateBodySuggestedFixOneSetupCommandsItemMax = 500

export const tasksRunsAnalysisInsightCreateBodySuggestedFixOneSetupCommandsMax = 10

export const tasksRunsAnalysisInsightCreateBodySuggestedFixOneRequiredServicesItemMax = 100

export const tasksRunsAnalysisInsightCreateBodySuggestedFixOneRequiredServicesMax = 10

export const tasksRunsAnalysisInsightCreateBodySuggestedFixOneEnvVarNamesItemMax = 100

export const tasksRunsAnalysisInsightCreateBodySuggestedFixOneEnvVarNamesMax = 10

export const TasksRunsAnalysisInsightCreateBody = /* @__PURE__ */ zod
    .object({
        no_findings_reason: zod
            .enum(['run_was_efficient', 'too_short_to_judge', 'insufficient_visibility'])
            .describe(
                '\* `run_was_efficient` - run_was_efficient\n\* `too_short_to_judge` - too_short_to_judge\n\* `insufficient_visibility` - insufficient_visibility'
            )
            .optional()
            .describe(
                'Only for a run with zero findings; never combined with a finding.\n\n\* `run_was_efficient` - run_was_efficient\n\* `too_short_to_judge` - too_short_to_judge\n\* `insufficient_visibility` - insufficient_visibility'
            ),
        observation: zod
            .string()
            .min(tasksRunsAnalysisInsightCreateBodyObservationMin)
            .max(tasksRunsAnalysisInsightCreateBodyObservationMax)
            .optional()
            .describe('What happened, 1-3 sentences.'),
        evidence: zod
            .array(
                zod.object({
                    quote: zod
                        .string()
                        .min(tasksRunsAnalysisInsightCreateBodyEvidenceItemQuoteMin)
                        .max(tasksRunsAnalysisInsightCreateBodyEvidenceItemQuoteMax)
                        .describe('Verbatim span copied from the analysed run log.'),
                    evidence_type: zod
                        .enum(['transcript_quote', 'command_output', 'measured_count'])
                        .describe(
                            '\* `transcript_quote` - transcript_quote\n\* `command_output` - command_output\n\* `measured_count` - measured_count'
                        )
                        .describe(
                            'What kind of log content the quote was taken from.\n\n\* `transcript_quote` - transcript_quote\n\* `command_output` - command_output\n\* `measured_count` - measured_count'
                        ),
                })
            )
            .optional()
            .describe('Quotes from the analysed log backing the observation.'),
        occurrence_count: zod.number().min(1).optional().describe('How often this happened.'),
        category: zod
            .enum([
                'environment_failure',
                'missing_tool',
                'verbose_output',
                'redundant_work',
                'missing_capability',
                'instruction_gap',
                'wasted_retry',
                'other',
            ])
            .describe(
                '\* `environment_failure` - environment_failure\n\* `missing_tool` - missing_tool\n\* `verbose_output` - verbose_output\n\* `redundant_work` - redundant_work\n\* `missing_capability` - missing_capability\n\* `instruction_gap` - instruction_gap\n\* `wasted_retry` - wasted_retry\n\* `other` - other'
            )
            .optional()
            .describe(
                'The kind of inefficiency observed.\n\n\* `environment_failure` - environment_failure\n\* `missing_tool` - missing_tool\n\* `verbose_output` - verbose_output\n\* `redundant_work` - redundant_work\n\* `missing_capability` - missing_capability\n\* `instruction_gap` - instruction_gap\n\* `wasted_retry` - wasted_retry\n\* `other` - other'
            ),
        other_justification: zod
            .string()
            .min(tasksRunsAnalysisInsightCreateBodyOtherJustificationMin)
            .max(tasksRunsAnalysisInsightCreateBodyOtherJustificationMax)
            .optional()
            .describe("Required when category is 'other'."),
        wasted_effort: zod
            .object({
                tool_calls: zod.number().min(1).optional().describe('Wasted tool calls, counted from the log.'),
                seconds: zod.number().min(1).optional().describe('Wall-clock seconds across the wasted span.'),
                tokens: zod.number().min(1).optional().describe('Token delta across the wasted span.'),
                output_bytes: zod
                    .number()
                    .min(1)
                    .optional()
                    .describe('Sum of tool-output sizes across the wasted span.'),
            })
            .optional()
            .describe('Effort measured from the log, never estimated.'),
        recurrence: zod
            .enum(['every_run_in_this_repo', 'runs_touching_this_area', 'one_off'])
            .describe(
                '\* `every_run_in_this_repo` - every_run_in_this_repo\n\* `runs_touching_this_area` - runs_touching_this_area\n\* `one_off` - one_off'
            )
            .optional()
            .describe(
                'How widely this is expected to recur.\n\n\* `every_run_in_this_repo` - every_run_in_this_repo\n\* `runs_touching_this_area` - runs_touching_this_area\n\* `one_off` - one_off'
            ),
        confidence_basis: zod
            .enum(['directly_observed', 'inferred'])
            .describe('\* `directly_observed` - directly_observed\n\* `inferred` - inferred')
            .optional()
            .describe(
                'How the finding was established.\n\n\* `directly_observed` - directly_observed\n\* `inferred` - inferred'
            ),
        suggested_fix: zod
            .object({
                change: zod
                    .string()
                    .min(tasksRunsAnalysisInsightCreateBodySuggestedFixOneChangeMin)
                    .max(tasksRunsAnalysisInsightCreateBodySuggestedFixOneChangeMax)
                    .describe('The specific change to make.'),
                done_when: zod
                    .string()
                    .min(tasksRunsAnalysisInsightCreateBodySuggestedFixOneDoneWhenMin)
                    .max(tasksRunsAnalysisInsightCreateBodySuggestedFixOneDoneWhenMax)
                    .describe('A checkable condition confirming the fix worked.'),
                setup_commands: zod
                    .array(
                        zod.string().min(1).max(tasksRunsAnalysisInsightCreateBodySuggestedFixOneSetupCommandsItemMax)
                    )
                    .max(tasksRunsAnalysisInsightCreateBodySuggestedFixOneSetupCommandsMax)
                    .optional()
                    .describe('Single-line commands only; these may become image build steps.'),
                required_services: zod
                    .array(
                        zod
                            .string()
                            .min(1)
                            .max(tasksRunsAnalysisInsightCreateBodySuggestedFixOneRequiredServicesItemMax)
                    )
                    .max(tasksRunsAnalysisInsightCreateBodySuggestedFixOneRequiredServicesMax)
                    .optional()
                    .describe('Services the fix needs available.'),
                env_var_names: zod
                    .array(zod.string().min(1).max(tasksRunsAnalysisInsightCreateBodySuggestedFixOneEnvVarNamesItemMax))
                    .max(tasksRunsAnalysisInsightCreateBodySuggestedFixOneEnvVarNamesMax)
                    .optional()
                    .describe('Environment variable names only, never values.'),
            })
            .optional()
            .describe('The fix the finding argues for.'),
    })
    .describe('One analysis finding. The shape the server stores, independent of what the tool sent.')

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

export const tasksRunsArtifactsCreateBodyArtifactsItemMetadataOneSkillNameMax = 255

export const tasksRunsArtifactsCreateBodyArtifactsItemMetadataOneContentSha256RegExp = new RegExp('^[a-f0-9]{64}$')

export const TasksRunsArtifactsCreateBody = /* @__PURE__ */ zod.object({
    artifacts: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .max(tasksRunsArtifactsCreateBodyArtifactsItemNameMax)
                    .describe('File name to associate with the artifact'),
                type: zod
                    .enum([
                        'plan',
                        'context',
                        'reference',
                        'output',
                        'artifact',
                        'tree_snapshot',
                        'user_attachment',
                        'skill_bundle',
                    ])
                    .describe(
                        '\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
                    )
                    .describe(
                        'Classification for the artifact\n\n\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
                    ),
                source: zod
                    .string()
                    .max(tasksRunsArtifactsCreateBodyArtifactsItemSourceMax)
                    .default(tasksRunsArtifactsCreateBodyArtifactsItemSourceDefault)
                    .describe('Optional source label for the artifact, such as agent_output or user_attachment'),
                content: zod.string().describe('Artifact contents encoded according to content_encoding'),
                content_encoding: zod
                    .enum(['utf-8', 'base64'])
                    .describe('\* `utf-8` - utf-8\n\* `base64` - base64')
                    .default(tasksRunsArtifactsCreateBodyArtifactsItemContentEncodingDefault)
                    .describe(
                        'Encoding used for content. Use base64 for binary files and utf-8 for text payloads.\n\n\* `utf-8` - utf-8\n\* `base64` - base64'
                    ),
                content_type: zod
                    .string()
                    .max(tasksRunsArtifactsCreateBodyArtifactsItemContentTypeMax)
                    .optional()
                    .describe('Optional MIME type for the artifact'),
                metadata: zod
                    .object({
                        skill_name: zod
                            .string()
                            .max(tasksRunsArtifactsCreateBodyArtifactsItemMetadataOneSkillNameMax)
                            .describe('Name of the local skill included in a skill_bundle artifact.'),
                        skill_source: zod
                            .enum(['user', 'repo', 'marketplace', 'codex'])
                            .describe(
                                '\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
                            )
                            .describe(
                                'Local source for the uploaded skill bundle, such as user or repo.\n\n\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
                            ),
                        content_sha256: zod
                            .string()
                            .regex(tasksRunsArtifactsCreateBodyArtifactsItemMetadataOneContentSha256RegExp)
                            .describe('SHA-256 hex digest of the uploaded skill bundle bytes.'),
                        bundle_format: zod
                            .enum(['zip'])
                            .describe('\* `zip` - zip')
                            .describe('Archive format used for the local skill bundle.\n\n\* `zip` - zip'),
                        schema_version: zod
                            .number()
                            .min(1)
                            .describe('Version of the local skill bundle metadata schema.'),
                    })
                    .optional()
                    .describe('Skill bundle metadata, required when the artifact type is skill_bundle.'),
            })
        )
        .describe('Array of artifacts to upload'),
})

/**
 * Hides artifacts from clients without deleting them from storage, so a file dismissed by mistake can be restored.
 * @summary Dismiss or restore task run artifacts
 */
export const tasksRunsArtifactsDismissCreateBodyArtifactIdsItemMax = 128

export const tasksRunsArtifactsDismissCreateBodyArtifactIdsMax = 100

export const tasksRunsArtifactsDismissCreateBodyDismissedDefault = true

export const TasksRunsArtifactsDismissCreateBody = /* @__PURE__ */ zod.object({
    artifact_ids: zod
        .array(zod.string().max(tasksRunsArtifactsDismissCreateBodyArtifactIdsItemMax))
        .max(tasksRunsArtifactsDismissCreateBodyArtifactIdsMax)
        .describe(
            'Manifest ids of the artifacts to update. Pass every version of a file together so the whole file is dismissed rather than a single upload of it.'
        ),
    dismissed: zod
        .boolean()
        .default(tasksRunsArtifactsDismissCreateBodyDismissedDefault)
        .describe('True to hide the artifacts from clients, false to show them again.'),
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

export const tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemMetadataOneSkillNameMax = 255

export const tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemMetadataOneContentSha256RegExp = new RegExp(
    '^[a-f0-9]{64}$'
)

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
                    .enum([
                        'plan',
                        'context',
                        'reference',
                        'output',
                        'artifact',
                        'tree_snapshot',
                        'user_attachment',
                        'skill_bundle',
                    ])
                    .describe(
                        '\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
                    )
                    .describe(
                        'Classification for the artifact\n\n\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
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
                metadata: zod
                    .object({
                        skill_name: zod
                            .string()
                            .max(tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemMetadataOneSkillNameMax)
                            .describe('Name of the local skill included in a skill_bundle artifact.'),
                        skill_source: zod
                            .enum(['user', 'repo', 'marketplace', 'codex'])
                            .describe(
                                '\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
                            )
                            .describe(
                                'Local source for the uploaded skill bundle, such as user or repo.\n\n\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
                            ),
                        content_sha256: zod
                            .string()
                            .regex(
                                tasksRunsArtifactsFinalizeUploadCreateBodyArtifactsItemMetadataOneContentSha256RegExp
                            )
                            .describe('SHA-256 hex digest of the uploaded skill bundle bytes.'),
                        bundle_format: zod
                            .enum(['zip'])
                            .describe('\* `zip` - zip')
                            .describe('Archive format used for the local skill bundle.\n\n\* `zip` - zip'),
                        schema_version: zod
                            .number()
                            .min(1)
                            .describe('Version of the local skill bundle metadata schema.'),
                    })
                    .optional()
                    .describe('Skill bundle metadata, required when the artifact type is skill_bundle.'),
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

export const tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemMetadataOneSkillNameMax = 255

export const tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemMetadataOneContentSha256RegExp = new RegExp(
    '^[a-f0-9]{64}$'
)

export const TasksRunsArtifactsPrepareUploadCreateBody = /* @__PURE__ */ zod.object({
    artifacts: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .max(tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemNameMax)
                    .describe('File name to associate with the artifact'),
                type: zod
                    .enum([
                        'plan',
                        'context',
                        'reference',
                        'output',
                        'artifact',
                        'tree_snapshot',
                        'user_attachment',
                        'skill_bundle',
                    ])
                    .describe(
                        '\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
                    )
                    .describe(
                        'Classification for the artifact\n\n\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
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
                metadata: zod
                    .object({
                        skill_name: zod
                            .string()
                            .max(tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemMetadataOneSkillNameMax)
                            .describe('Name of the local skill included in a skill_bundle artifact.'),
                        skill_source: zod
                            .enum(['user', 'repo', 'marketplace', 'codex'])
                            .describe(
                                '\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
                            )
                            .describe(
                                'Local source for the uploaded skill bundle, such as user or repo.\n\n\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
                            ),
                        content_sha256: zod
                            .string()
                            .regex(tasksRunsArtifactsPrepareUploadCreateBodyArtifactsItemMetadataOneContentSha256RegExp)
                            .describe('SHA-256 hex digest of the uploaded skill bundle bytes.'),
                        bundle_format: zod
                            .enum(['zip'])
                            .describe('\* `zip` - zip')
                            .describe('Archive format used for the local skill bundle.\n\n\* `zip` - zip'),
                        schema_version: zod
                            .number()
                            .min(1)
                            .describe('Version of the local skill bundle metadata schema.'),
                    })
                    .optional()
                    .describe('Skill bundle metadata, required when the artifact type is skill_bundle.'),
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
 * Attach live PostHog object references to the run artifact manifest without uploading files.
 * @summary Register PostHog object references for a task run
 */
export const tasksRunsArtifactsReferencesCreateBodyReferencesItemNameMax = 255

export const tasksRunsArtifactsReferencesCreateBodyReferencesItemObjectIdMax = 16384

export const tasksRunsArtifactsReferencesCreateBodyReferencesItemSourceMessageIdMax = 255

export const tasksRunsArtifactsReferencesCreateBodyReferencesMax = 50

export const TasksRunsArtifactsReferencesCreateBody = /* @__PURE__ */ zod.object({
    references: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .max(tasksRunsArtifactsReferencesCreateBodyReferencesItemNameMax)
                    .describe('Fallback display name for the referenced object.'),
                object_kind: zod
                    .enum([
                        'insight',
                        'hogql',
                        'dashboard',
                        'error',
                        'replay',
                        'flag',
                        'experiment',
                        'survey',
                        'ticket',
                        'trace',
                        'eval',
                        'event',
                        'cohort',
                        'action',
                        'person',
                    ])
                    .describe(
                        '\* `insight` - insight\n\* `hogql` - hogql\n\* `dashboard` - dashboard\n\* `error` - error\n\* `replay` - replay\n\* `flag` - flag\n\* `experiment` - experiment\n\* `survey` - survey\n\* `ticket` - ticket\n\* `trace` - trace\n\* `eval` - eval\n\* `event` - event\n\* `cohort` - cohort\n\* `action` - action\n\* `person` - person'
                    )
                    .describe(
                        'PostHog object kind used to resolve the reference.\n\n\* `insight` - insight\n\* `hogql` - hogql\n\* `dashboard` - dashboard\n\* `error` - error\n\* `replay` - replay\n\* `flag` - flag\n\* `experiment` - experiment\n\* `survey` - survey\n\* `ticket` - ticket\n\* `trace` - trace\n\* `eval` - eval\n\* `event` - event\n\* `cohort` - cohort\n\* `action` - action\n\* `person` - person'
                    ),
                object_id: zod
                    .string()
                    .max(tasksRunsArtifactsReferencesCreateBodyReferencesItemObjectIdMax)
                    .describe('Exact PostHog object identifier, flag key, event name, or SQL query.'),
                source_message_id: zod
                    .string()
                    .max(tasksRunsArtifactsReferencesCreateBodyReferencesItemSourceMessageIdMax)
                    .describe('Stable identifier of the completed assistant message containing the reference.'),
            })
        )
        .max(tasksRunsArtifactsReferencesCreateBodyReferencesMax)
        .describe('PostHog object references extracted from one completed assistant message.'),
})

/**
 * Stop an active cloud run. Interrupts the agent, snapshots interactive sessions for later resume, tears down the sandbox, and marks the run cancelled. Idempotent: cancelling a finished run returns it unchanged.
 * @summary Cancel task run
 */
export const tasksRunsCancelCreateBodyReasonMax = 500

export const tasksRunsCancelCreateBodyOnlyIfAwaitingFirstMessageDefault = false

export const TasksRunsCancelCreateBody = /* @__PURE__ */ zod.object({
    reason: zod
        .string()
        .max(tasksRunsCancelCreateBodyReasonMax)
        .nullish()
        .describe('Optional reason for the cancellation, recorded on the run and shown to run watchers.'),
    only_if_awaiting_first_message: zod
        .boolean()
        .default(tasksRunsCancelCreateBodyOnlyIfAwaitingFirstMessageDefault)
        .describe(
            'Cancel only while the run is still a warm sandbox awaiting its first message. A run that has since received one is left alone and returned unchanged. Set this when handing a warm sandbox back, so a release that races a submit cannot stop the run that submit started.'
        ),
})

/**
 * Queue user_message JSON-RPC commands through the task workflow and forward sandbox control commands to the agent server. Supports user_message, cancel, close, permission_response, set_config_option, mcp_response, side_question, native Pi RPC commands, and Pi queue operations.
 * @summary Send command to task run
 */
export const TasksRunsCommandCreateBody = /* @__PURE__ */ zod
    .object({
        jsonrpc: zod
            .enum(['2.0'])
            .describe('\* `2.0` - 2.0')
            .describe("JSON-RPC version, must be '2.0'\n\n\* `2.0` - 2.0"),
        method: zod
            .enum([
                'user_message',
                'cancel',
                'close',
                'permission_response',
                'set_config_option',
                'mcp_response',
                'pi/rpc',
                'queue_get',
                'queue_clear',
                'side_question',
            ])
            .describe(
                '\* `user_message` - user_message\n\* `cancel` - cancel\n\* `close` - close\n\* `permission_response` - permission_response\n\* `set_config_option` - set_config_option\n\* `mcp_response` - mcp_response\n\* `pi\/rpc` - pi\/rpc\n\* `queue_get` - queue_get\n\* `queue_clear` - queue_clear\n\* `side_question` - side_question'
            )
            .describe(
                'Command method to execute on the agent server\n\n\* `user_message` - user_message\n\* `cancel` - cancel\n\* `close` - close\n\* `permission_response` - permission_response\n\* `set_config_option` - set_config_option\n\* `mcp_response` - mcp_response\n\* `pi\/rpc` - pi\/rpc\n\* `queue_get` - queue_get\n\* `queue_clear` - queue_clear\n\* `side_question` - side_question'
            ),
        params: zod.record(zod.string(), zod.unknown()).optional().describe('Parameters for the command'),
        id: zod.unknown().optional().describe('Optional JSON-RPC request ID (string or number)'),
    })
    .describe('JSON-RPC request to send a command to the agent server in the sandbox.')

/**
 * Relay a message from this run to a peer agent run. The body is delivered below a server-composed provenance envelope as a queued (non-steer) turn; attachments are copied into the target run's own artifact storage. `accepted` means queued for delivery, never delivered — the sandbox handoff happens later inside the target's workflow.
 * @summary Send a message to a peer agent run
 */
export const tasksRunsPeersMessageCreateBodyContentMax = 16000

export const tasksRunsPeersMessageCreateBodyArtifactIdsItemMax = 128

export const tasksRunsPeersMessageCreateBodyArtifactIdsMax = 10

export const TasksRunsPeersMessageCreateBody = /* @__PURE__ */ zod.object({
    content: zod
        .string()
        .max(tasksRunsPeersMessageCreateBodyContentMax)
        .describe(
            'Plain-text message body (max 16000 chars). Delivered to the peer below a server-composed provenance envelope; send short summaries, never raw file dumps — use artifact_ids for files.'
        ),
    artifact_ids: zod
        .array(zod.string().max(tasksRunsPeersMessageCreateBodyArtifactIdsItemMax))
        .max(tasksRunsPeersMessageCreateBodyArtifactIdsMax)
        .optional()
        .describe(
            "Manifest ids of artifacts on the SENDING run to share (max 10). Each is copied into the target run's own artifact storage; the receiver gets an immutable snapshot."
        ),
})

/**
 * Queue a Slack relay workflow to post a run message into the mapped Slack thread.
 * @summary Relay run message to Slack
 */
export const tasksRunsRelayMessageCreateBodyTextMax = 10000

export const tasksRunsRelayMessageCreateBodyMessageIdMax = 128

export const tasksRunsRelayMessageCreateBodyTextPartsItemMax = 10000

export const TasksRunsRelayMessageCreateBody = /* @__PURE__ */ zod.object({
    text: zod
        .string()
        .max(tasksRunsRelayMessageCreateBodyTextMax)
        .describe('Joined message body. Used when text_parts is absent.'),
    message_id: zod
        .string()
        .max(tasksRunsRelayMessageCreateBodyMessageIdMax)
        .nullish()
        .describe('Id of the user message this turn answers, when the agent-server echoes it.'),
    text_parts: zod
        .array(zod.string().max(tasksRunsRelayMessageCreateBodyTextPartsItemMax))
        .optional()
        .describe('Ordered assistant text blocks. When present, the last non-empty entry is posted instead of text.'),
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

/**
 * Create a stable, editable artifact handle from direct markdown/text content or an existing run artifact. Slack adapters deliver into the mapped Slack thread; document artifacts use external connector storage when available.
 * @summary Create a living artifact for a task run
 */
export const tasksRunsLivingArtifactsCreateBodyNameMax = 255

export const tasksRunsLivingArtifactsCreateBodyArtifactTypeDefault = `document`
export const tasksRunsLivingArtifactsCreateBodyContentMax = 500000

export const tasksRunsLivingArtifactsCreateBodyContentTypeMax = 255

export const TasksRunsLivingArtifactsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(tasksRunsLivingArtifactsCreateBodyNameMax)
        .describe('Human-readable artifact name, used as the title.'),
    artifact_type: zod
        .enum(['slack_message', 'slack_canvas', 'document', 'spreadsheet', 'dashboard', 'file', 'github_pr'])
        .describe(
            '\* `slack_message` - slack_message\n\* `slack_canvas` - slack_canvas\n\* `document` - document\n\* `spreadsheet` - spreadsheet\n\* `dashboard` - dashboard\n\* `file` - file\n\* `github_pr` - github_pr'
        )
        .default(tasksRunsLivingArtifactsCreateBodyArtifactTypeDefault)
        .describe(
            'Artifact format or delivery surface to create, such as document, spreadsheet, slack_canvas, or file.\n\n\* `slack_message` - slack_message\n\* `slack_canvas` - slack_canvas\n\* `document` - document\n\* `spreadsheet` - spreadsheet\n\* `dashboard` - dashboard\n\* `file` - file\n\* `github_pr` - github_pr'
        ),
    adapter: zod
        .enum(['slack_message', 'slack_canvas', 'slack_file', 'document_connector', 'github_pr'])
        .describe(
            '\* `slack_message` - slack_message\n\* `slack_canvas` - slack_canvas\n\* `slack_file` - slack_file\n\* `document_connector` - document_connector\n\* `github_pr` - github_pr'
        )
        .optional()
        .describe(
            'Optional preferred external storage or delivery adapter. Slack adapters deliver into the mapped Slack thread; omitted Slack-run documents use Slack canvas, omitted Slack-run files and spreadsheets use Slack file upload, and document_connector uses a connected external document provider.\n\n\* `slack_message` - slack_message\n\* `slack_canvas` - slack_canvas\n\* `slack_file` - slack_file\n\* `document_connector` - document_connector\n\* `github_pr` - github_pr'
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
            'Base64-encoded binary content for Slack file uploads or other external adapters. Prefer source_artifact_id or source_storage_path for large files that were already uploaded as run output artifacts.'
        ),
    content_type: zod
        .string()
        .max(tasksRunsLivingArtifactsCreateBodyContentTypeMax)
        .optional()
        .describe(
            'MIME type for content_base64 or source-backed artifacts, such as application\/vnd.openxmlformats-officedocument.spreadsheetml.sheet.'
        ),
    source_artifact_id: zod
        .string()
        .optional()
        .describe(
            'Existing run artifact id to use as the initial content source. Only agent-uploaded output artifacts are accepted; internal run artifacts are rejected.'
        ),
    source_storage_path: zod
        .string()
        .optional()
        .describe(
            'Existing run artifact storage_path to use as the initial content source. Only agent-uploaded output artifacts are accepted; internal run artifacts are rejected.'
        ),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Optional metadata to persist with the living artifact.'),
})

/**
 * Commit a new version to an existing living artifact handle.
 * @summary Edit a living artifact for a task run
 */
export const tasksRunsLivingArtifactsEditBodyNameMax = 255

export const tasksRunsLivingArtifactsEditBodyContentMax = 500000

export const tasksRunsLivingArtifactsEditBodyContentTypeMax = 255

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
        .describe(
            'Existing run artifact id to use as the next version content source. Only agent-uploaded output artifacts are accepted; internal run artifacts are rejected.'
        ),
    source_storage_path: zod
        .string()
        .optional()
        .describe(
            'Existing run artifact storage_path to use as the next version content source. Only agent-uploaded output artifacts are accepted; internal run artifacts are rejected.'
        ),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Optional metadata to merge into the artifact registry record.'),
})

/**
 * Renders a PostHog insight (ad-hoc query JSON or a saved insight) to a PNG server-side and registers it as a slack_file living artifact in one call. Blocks until the render finishes.
 * @summary Render an insight chart and attach it as a living artifact
 */
export const tasksRunsLivingArtifactsChartBodyNameMax = 255

export const TasksRunsLivingArtifactsChartBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(tasksRunsLivingArtifactsChartBodyNameMax)
        .describe('Chart title, also used as the delivered file name.'),
    query: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Insight query JSON to render ad hoc, e.g. {\"kind\": \"InsightVizNode\", \"source\": {\"kind\": \"TrendsQuery\", ...}}. SQL queries (DataVisualizationNode, HogQLQuery) are not supported yet. Provide exactly one of query or insight_id.'
        ),
    insight_id: zod
        .number()
        .optional()
        .describe('Numeric id of a saved insight to render. Provide exactly one of query or insight_id.'),
})

/**
 * API for a task's thread — the human-only side conversation around a task. Messages
 * reach the agent only via the explicit send_to_agent action, gated to the task author.
 * @summary Post a thread message
 */
export const TasksThreadMessagesCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string().describe('Message text.'),
    })
    .describe('Request body for posting a thread message.')

/**
 * Task author only: forwards the message into the task's latest live run.
 * @summary Send a thread message to the agent
 */
export const TasksThreadMessagesSendToAgentCreateBody = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        task: zod.uuid(),
        author_kind: zod.string(),
        event: zod.string(),
        payload: zod.record(zod.string(), zod.unknown()),
        content: zod.string(),
        created_at: zod.iso.datetime({ offset: true }),
        author: zod
            .union([
                zod
                    .object({
                        id: zod.number(),
                        uuid: zod.uuid(),
                        distinct_id: zod.string(),
                        first_name: zod.string(),
                        last_name: zod.string(),
                        email: zod.string(),
                        is_email_verified: zod.boolean().nullish(),
                        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
                        role_at_organization: zod.string().nullish(),
                    })
                    .describe('Response shape for a task creator, mirroring core ``UserBasicSerializer`` output.'),
                zod.null(),
            ])
            .optional(),
        forwarded_to_agent_at: zod.iso.datetime({ offset: true }).nullish(),
        forwarded_by: zod
            .union([
                zod
                    .object({
                        id: zod.number(),
                        uuid: zod.uuid(),
                        distinct_id: zod.string(),
                        first_name: zod.string(),
                        last_name: zod.string(),
                        email: zod.string(),
                        is_email_verified: zod.boolean().nullish(),
                        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
                        role_at_organization: zod.string().nullish(),
                    })
                    .describe('Response shape for a task creator, mirroring core ``UserBasicSerializer`` output.'),
                zod.null(),
            ])
            .optional(),
    })
    .describe("Response shape for one message in a task's thread.")

/**
 * Returns summary for the requested tasks: `id`, `title`, `repository`, `created_at`, `updated_at`, and the latest run's `status` and `environment`.
 * @summary Fetch task summaries by ID
 */
export const tasksSummariesCreateBodyIdsMax = 5000

export const TasksSummariesCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.uuid())
        .max(tasksSummariesCreateBodyIdsMax)
        .describe(
            'Task IDs to fetch summaries for (max 5000). Response is paginated; follow the `next` cursor to retrieve all results.'
        ),
})

/**
 * Warm a full idling Run for a cloud task while the user composes: boot a sandbox, clone the repo, check out the branch, and start the agent, then idle awaiting the first message. On submit the normal create+run path transparently reuses and activates this Run; abandoned warms are reaped by the Run's inactivity timeout. Best-effort: returns an empty body when the feature flag is off, the warm pool is full, or the GitHub integration doesn't belong to the team.
 * @summary Warm a task sandbox
 */
export const tasksWarmCreateBodyRepositoryMax = 255

export const tasksWarmCreateBodyRepositoriesItemMax = 255

export const tasksWarmCreateBodyRepositoriesMax = 3

export const tasksWarmCreateBodyBranchMax = 255

export const tasksWarmCreateBodyOriginProductDefault = `user_created`

export const TasksWarmCreateBody = /* @__PURE__ */ zod
    .object({
        repository: zod
            .string()
            .max(tasksWarmCreateBodyRepositoryMax)
            .nullish()
            .describe('Optional GitHub repository to clone, in `organization\/repo` format (e.g. `posthog\/posthog`).'),
        repositories: zod
            .array(zod.string().max(tasksWarmCreateBodyRepositoriesItemMax))
            .max(tasksWarmCreateBodyRepositoriesMax)
            .optional()
            .describe('GitHub repositories to clone into the warm sandbox, each in `organization\/repo` format.'),
        github_integration: zod
            .number()
            .nullish()
            .describe("Primary key of the team's GitHub integration to clone with when a repository is selected."),
        branch: zod
            .string()
            .max(tasksWarmCreateBodyBranchMax)
            .nullish()
            .describe(
                "Branch to check out in the warm sandbox. Defaults to the repository's default branch when omitted."
            ),
        runtime_adapter: zod
            .union([zod.enum(['claude', 'codex']).describe('\* `claude` - claude\n\* `codex` - codex'), zod.null()])
            .optional()
            .describe(
                "Agent runtime adapter to warm the sandbox on ('claude' or 'codex'). The warm Run starts the agent on this runtime so a matching submit reuses it; a submit selecting a different runtime falls through to a cold Run instead of reusing a mismatched warm session.\n\n\* `claude` - claude\n\* `codex` - codex"
            ),
        model: zod
            .string()
            .nullish()
            .describe(
                "LLM model identifier to warm the sandbox on. A submit selecting a different model won't reuse this warm Run."
            ),
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
                'Reasoning effort to warm the sandbox on for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
            ),
        sandbox_environment_id: zod
            .uuid()
            .nullish()
            .describe('Optional sandbox environment to provision before the task is submitted.'),
        custom_image_id: zod
            .uuid()
            .nullish()
            .describe(
                "Optional custom base image to provision before the task is submitted; takes precedence over the environment's image."
            ),
        origin_product: zod
            .enum(['user_created', 'posthog_ai'])
            .describe('\* `user_created` - user_created\n\* `posthog_ai` - posthog_ai')
            .default(tasksWarmCreateBodyOriginProductDefault)
            .describe(
                'Product the warm Run is for. Fixed when the sandbox boots — it selects the OAuth app, the quota gate, the warm-pool budget, and PR authorship — so a submit only reuses a warm born under the same origin. Defaults to the Code app.\n\n\* `user_created` - user_created\n\* `posthog_ai` - posthog_ai'
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
                "Permission mode to boot the agent session on. Read at session construction, so it cannot be changed once the sandbox is warm — a submit selecting a different mode falls through to a cold Run. Omit to take the runtime's default.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access"
            ),
    })
    .describe(
        "Request body for warming a full idling Run while composing a Code-app cloud task.\n\nCollection-level: no task exists yet at typing time. The warmer births a draft Task and an\ninteractive Run that boots and starts the agent, optionally cloning and checking out a repository,\nthen idles awaiting the first message. `github_integration` is a plain integration PK (an integer);\nthe view re-scopes it to the caller's team before use."
    )
