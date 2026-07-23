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
                    .enum(['low', 'medium', 'high', 'xhigh', 'max'])
                    .describe(
                        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "Reasoning effort, validated against `runtime_adapter`\/`model`'s supported set.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max"
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
                    folder_id: zod.string().describe('Desktop folder id of the context this loop is attached to.'),
                    name: zod
                        .string()
                        .max(loopsCreateBodyContextTargetOneNameMax)
                        .describe('Context (channel) name, used to file runs into its feed.'),
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
                            'Trigger configuration, shape validated per `type`: schedule takes `{cron_expression, timezone}` or `{run_at}` for a one-time run; github takes `{github_integration_id, repository, events, filters}` where `events` is one or more of `issues`, `issue_comment`, `pull_request`, `push` (`event.action` shorthand like `issues.opened` is folded into an `actions` filter, one event per trigger) and `filters` takes `{actions, branches, labels}`; api takes no config.'
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
                    .enum(['low', 'medium', 'high', 'xhigh', 'max'])
                    .describe(
                        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "Reasoning effort, validated against `runtime_adapter`\/`model`'s supported set.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max"
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
                    folder_id: zod.string().describe('Desktop folder id of the context this loop is attached to.'),
                    name: zod
                        .string()
                        .max(loopsPartialUpdateBodyContextTargetOneNameMax)
                        .describe('Context (channel) name, used to file runs into its feed.'),
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
                            'Trigger configuration, shape validated per `type`: schedule takes `{cron_expression, timezone}` or `{run_at}` for a one-time run; github takes `{github_integration_id, repository, events, filters}` where `events` is one or more of `issues`, `issue_comment`, `pull_request`, `push` (`event.action` shorthand like `issues.opened` is folded into an `actions` filter, one event per trigger) and `filters` takes `{actions, branches, labels}`; api takes no config.'
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
 * API for managing scheduled task automations.
 */
export const taskAutomationsCreateBodyNameMax = 255

export const taskAutomationsCreateBodyRepositoryMax = 255

export const taskAutomationsCreateBodyCronExpressionMax = 100

export const taskAutomationsCreateBodyTimezoneDefault = `UTC`
export const taskAutomationsCreateBodyTimezoneMax = 128

export const taskAutomationsCreateBodyTemplateIdMax = 255

export const taskAutomationsCreateBodyEnabledDefault = true

export const TaskAutomationsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(taskAutomationsCreateBodyNameMax)
            .describe("Display name (stored as the backing task's title)."),
        prompt: zod.string().describe("The automation prompt (stored as the backing task's description)."),
        repository: zod
            .string()
            .max(taskAutomationsCreateBodyRepositoryMax)
            .describe('Target repository in the format organization\/repository.'),
        github_integration: zod
            .number()
            .nullish()
            .describe("GitHub integration to run as. Defaults to the team's GitHub integration when omitted."),
        cron_expression: zod
            .string()
            .max(taskAutomationsCreateBodyCronExpressionMax)
            .describe('Standard 5-field cron expression (minute hour day month weekday).'),
        timezone: zod
            .string()
            .max(taskAutomationsCreateBodyTimezoneMax)
            .default(taskAutomationsCreateBodyTimezoneDefault)
            .describe('IANA timezone the schedule runs in.'),
        template_id: zod
            .string()
            .max(taskAutomationsCreateBodyTemplateIdMax)
            .nullish()
            .describe('Optional template identifier this automation was created from.'),
        enabled: zod
            .boolean()
            .default(taskAutomationsCreateBodyEnabledDefault)
            .describe('Whether the schedule is active; paused when false.'),
    })
    .describe('Request body for creating or updating a task automation.')

/**
 * API for managing scheduled task automations.
 */
export const taskAutomationsPartialUpdateBodyNameMax = 255

export const taskAutomationsPartialUpdateBodyRepositoryMax = 255

export const taskAutomationsPartialUpdateBodyCronExpressionMax = 100

export const taskAutomationsPartialUpdateBodyTimezoneDefault = `UTC`
export const taskAutomationsPartialUpdateBodyTimezoneMax = 128

export const taskAutomationsPartialUpdateBodyTemplateIdMax = 255

export const taskAutomationsPartialUpdateBodyEnabledDefault = true

export const TaskAutomationsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(taskAutomationsPartialUpdateBodyNameMax)
            .optional()
            .describe("Display name (stored as the backing task's title)."),
        prompt: zod.string().optional().describe("The automation prompt (stored as the backing task's description)."),
        repository: zod
            .string()
            .max(taskAutomationsPartialUpdateBodyRepositoryMax)
            .optional()
            .describe('Target repository in the format organization\/repository.'),
        github_integration: zod
            .number()
            .nullish()
            .describe("GitHub integration to run as. Defaults to the team's GitHub integration when omitted."),
        cron_expression: zod
            .string()
            .max(taskAutomationsPartialUpdateBodyCronExpressionMax)
            .optional()
            .describe('Standard 5-field cron expression (minute hour day month weekday).'),
        timezone: zod
            .string()
            .max(taskAutomationsPartialUpdateBodyTimezoneMax)
            .default(taskAutomationsPartialUpdateBodyTimezoneDefault)
            .describe('IANA timezone the schedule runs in.'),
        template_id: zod
            .string()
            .max(taskAutomationsPartialUpdateBodyTemplateIdMax)
            .nullish()
            .describe('Optional template identifier this automation was created from.'),
        enabled: zod
            .boolean()
            .default(taskAutomationsPartialUpdateBodyEnabledDefault)
            .describe('Whether the schedule is active; paused when false.'),
    })
    .describe('Request body for creating or updating a task automation.')

/**
 * Returns the existing public channel with the (normalized) name, creating it if needed.
 * @summary Resolve or create a public channel
 */
export const taskChannelsCreateBodyNameMax = 128

export const TaskChannelsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(taskChannelsCreateBodyNameMax)
            .describe('Channel name, rendered as #<name>. Normalized to lowercase-dashed.'),
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
 * API for task channels — the shared feeds tasks are kicked off in. Listing lazily
 * provisions the requester's personal "#me" channel; creation is resolve-or-create
 * by normalized name so clients can map channel-like surfaces onto backend channels.
 * @summary Rename a public channel
 */
export const taskChannelsPartialUpdateBodyNameMax = 128

export const TaskChannelsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(taskChannelsPartialUpdateBodyNameMax)
            .optional()
            .describe('Channel name, rendered as #<name>. Normalized to lowercase-dashed.'),
    })
    .describe('Request body for creating (resolve-or-create) or renaming a public channel.')

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
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
                'loop',
            ])
            .describe(
                '\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `automation` - Automation\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop'
            )
            .optional()
            .describe(
                'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.\n\n\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `automation` - Automation\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop'
            ),
        repository: zod
            .string()
            .max(tasksCreateBodyRepositoryMax)
            .nullish()
            .describe('Target GitHub repository in `organization\/repo` format (e.g. `posthog\/posthog-js`).'),
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
                    .enum(['low', 'medium', 'high', 'xhigh', 'max'])
                    .describe(
                        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
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
                'loop',
            ])
            .describe(
                '\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `automation` - Automation\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop'
            )
            .optional()
            .describe(
                'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.\n\n\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `automation` - Automation\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop'
            ),
        repository: zod
            .string()
            .max(tasksUpdateBodyRepositoryMax)
            .nullish()
            .describe('Target GitHub repository in `organization\/repo` format (e.g. `posthog\/posthog-js`).'),
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
                    .enum(['low', 'medium', 'high', 'xhigh', 'max'])
                    .describe(
                        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
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
                'loop',
            ])
            .describe(
                '\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `automation` - Automation\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop'
            )
            .optional()
            .describe(
                'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.\n\n\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `automation` - Automation\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop'
            ),
        repository: zod
            .string()
            .max(tasksPartialUpdateBodyRepositoryMax)
            .nullish()
            .describe('Target GitHub repository in `organization\/repo` format (e.g. `posthog\/posthog-js`).'),
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
                    .enum(['low', 'medium', 'high', 'xhigh', 'max'])
                    .describe(
                        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
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
                    'Local url-based MCP servers from the creating client (PostHog Code) to make available inside the cloud sandbox. Header values are treated as credentials: stored encrypted and never returned by the API.'
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
                    'Names of desktop-only MCP servers the creating client (PostHog Code) relays into the cloud sandbox over the durable event\/command channel. Names only — the server configuration (command, env, URL, headers) never crosses the wire.'
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
                .enum(['low', 'medium', 'high', 'xhigh', 'max'])
                .describe('\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max')
                .optional()
                .describe(
                    'Reasoning effort to request for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
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
                    'Local url-based MCP servers from the creating client (PostHog Code) to make available inside the cloud sandbox. Header values are treated as credentials: stored encrypted and never returned by the API.'
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
                    'Names of desktop-only MCP servers the creating client (PostHog Code) relays into the cloud sandbox over the durable event\/command channel. Names only — the server configuration (command, env, URL, headers) never crosses the wire.'
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
                .enum(['low', 'medium', 'high', 'xhigh', 'max'])
                .describe('\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max')
                .optional()
                .describe(
                    'Reasoning effort to request for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
                ),
            github_user_token: zod
                .string()
                .optional()
                .describe(
                    'Optional GitHub user token from PostHog Code for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens.'
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
                    .describe('Optional structured metadata for special artifact types, such as skill bundles.'),
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
                    .describe('Optional structured metadata for special artifact types, such as skill bundles.'),
            })
        )
        .describe('Array of staged artifacts to prepare before creating a run'),
})

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
                'Local url-based MCP servers from the creating client (PostHog Code) to make available inside the cloud sandbox. Header values are treated as credentials: stored encrypted and never returned by the API.'
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
                'Names of desktop-only MCP servers the creating client (PostHog Code) relays into the cloud sandbox over the durable event\/command channel. Names only — the server configuration (command, env, URL, headers) never crosses the wire.'
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
            .enum(['low', 'medium', 'high', 'xhigh', 'max'])
            .describe('\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max')
            .optional()
            .describe(
                'Reasoning effort to request for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
            ),
        github_user_token: zod
            .string()
            .optional()
            .describe('Ephemeral GitHub user token from PostHog Code for user-authored cloud pull requests.'),
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
    error_message: zod.string().nullish().describe('Error message if execution failed'),
    environment: zod
        .enum(['local'])
        .describe('\* `local` - local')
        .optional()
        .describe(
            'Transition a cloud run to local. Use the resume_in_cloud action to move a run into cloud.\n\n\* `local` - local'
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
                    .describe('Optional structured metadata for special artifact types, such as skill bundles.'),
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
                    .describe('Optional structured metadata for special artifact types, such as skill bundles.'),
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
                    .describe('Optional structured metadata for special artifact types, such as skill bundles.'),
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
 * Stop an active cloud run. Interrupts the agent, snapshots interactive sessions for later resume, tears down the sandbox, and marks the run cancelled. Idempotent: cancelling a finished run returns it unchanged.
 * @summary Cancel task run
 */
export const tasksRunsCancelCreateBodyReasonMax = 500

export const TasksRunsCancelCreateBody = /* @__PURE__ */ zod.object({
    reason: zod
        .string()
        .max(tasksRunsCancelCreateBodyReasonMax)
        .nullish()
        .describe('Optional reason for the cancellation, recorded on the run and shown to run watchers.'),
})

/**
 * Queue user_message JSON-RPC commands through the task workflow and forward sandbox control commands to the agent server. Supports user_message, cancel, close, permission_response, set_config_option, and mcp_response commands.
 * @summary Send command to task run
 */
export const TasksRunsCommandCreateBody = /* @__PURE__ */ zod
    .object({
        jsonrpc: zod
            .enum(['2.0'])
            .describe('\* `2.0` - 2.0')
            .describe("JSON-RPC version, must be '2.0'\n\n\* `2.0` - 2.0"),
        method: zod
            .enum(['user_message', 'cancel', 'close', 'permission_response', 'set_config_option', 'mcp_response'])
            .describe(
                '\* `user_message` - user_message\n\* `cancel` - cancel\n\* `close` - close\n\* `permission_response` - permission_response\n\* `set_config_option` - set_config_option\n\* `mcp_response` - mcp_response'
            )
            .describe(
                'Command method to execute on the agent server\n\n\* `user_message` - user_message\n\* `cancel` - cancel\n\* `close` - close\n\* `permission_response` - permission_response\n\* `set_config_option` - set_config_option\n\* `mcp_response` - mcp_response'
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
 * Warm a full idling Run for a Code-app cloud task while the user composes: boot a sandbox, clone the repo, check out the branch, and start the agent, then idle awaiting the first message. On submit the normal create+run path transparently reuses and activates this Run; abandoned warms are reaped by the Run's inactivity timeout. Best-effort: returns an empty body when the feature flag is off, the warm pool is full, or the GitHub integration doesn't belong to the team.
 * @summary Warm a task sandbox
 */
export const tasksWarmCreateBodyRepositoryMax = 255

export const tasksWarmCreateBodyBranchMax = 255

export const TasksWarmCreateBody = /* @__PURE__ */ zod
    .object({
        repository: zod
            .string()
            .max(tasksWarmCreateBodyRepositoryMax)
            .describe('Target GitHub repository to clone, in `organization\/repo` format (e.g. `posthog\/posthog`).'),
        github_integration: zod.number().describe("Primary key of the team's GitHub integration to clone with."),
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
                    .enum(['low', 'medium', 'high', 'xhigh', 'max'])
                    .describe(
                        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Reasoning effort to warm the sandbox on for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
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
    })
    .describe(
        "Request body for warming a full idling Run while composing a Code-app cloud task.\n\nCollection-level: no task exists yet at typing time. The warmer births a draft Task and an\ninteractive Run that boots, clones, checks out `branch`, and starts the agent, then idles awaiting\nthe first message. `github_integration` is a plain integration PK (an integer); the view re-scopes\nit to the caller's team before use."
    )
