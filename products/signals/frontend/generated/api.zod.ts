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
 * View and control signal processing pipeline state for a team.
 */
export const SignalsProcessingPauseUpdateBody = /* @__PURE__ */ zod.object({
    timestamp: zod.iso
        .datetime({ offset: true })
        .describe('Pause the grouping pipeline until this timestamp (ISO 8601).'),
})

/**
 * Replace the contents of a signal report artefact. Currently only artefacts of type `suggested_reviewers` may be modified via this endpoint; other types return 400.
 */
export const signalsReportsArtefactsUpdateBodyContentItemGithubLoginMax = 200

export const signalsReportsArtefactsUpdateBodyContentItemGithubNameMax = 200

export const SignalsReportsArtefactsUpdateBody = /* @__PURE__ */ zod
    .object({
        content: zod
            .array(
                zod
                    .object({
                        github_login: zod
                            .string()
                            .max(signalsReportsArtefactsUpdateBodyContentItemGithubLoginMax)
                            .optional()
                            .describe('GitHub login (case-insensitive). Stored lowercased.'),
                        user_uuid: zod
                            .uuid()
                            .optional()
                            .describe(
                                'PostHog user UUID. Must be an org member on this team with a linked GitHub identity. If supplied together with `github_login`, the server-resolved login from the user wins.'
                            ),
                        github_name: zod
                            .string()
                            .max(signalsReportsArtefactsUpdateBodyContentItemGithubNameMax)
                            .optional()
                            .describe(
                                'Optional human-readable display name. Not backfilled from GitHub by the server.'
                            ),
                    })
                    .describe(
                        'Single entry in a PUT body for a `suggested_reviewers` artefact.\n\nEach entry must identify a reviewer by at least one of `github_login` or `user_uuid`.\nThe server canonicalizes to a lowercase `github_login` — if `user_uuid` is supplied,\nit must map to an org member on this team with a linked GitHub login.'
                    )
            )
            .describe('Full replacement list of reviewers. Empty list clears the artefact. At most 10 entries.'),
    })
    .describe(
        "PUT body for replacing a `suggested_reviewers` artefact's content.\n\nOnly `suggested_reviewers` artefacts may be modified via this endpoint;\nthe viewset enforces the type check before validation runs."
    )

export const SignalsSourceConfigsCreateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum([
            'session_replay',
            'llm_analytics',
            'github',
            'linear',
            'zendesk',
            'conversations',
            'error_tracking',
            'pganalyze',
        ])
        .describe(
            '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze'
        ),
    source_type: zod
        .enum([
            'session_analysis_cluster',
            'evaluation',
            'issue',
            'ticket',
            'issue_created',
            'issue_reopened',
            'issue_spiking',
        ])
        .describe(
            '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation` - Evaluation\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking'
        ),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
})

export const SignalsSourceConfigsUpdateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum([
            'session_replay',
            'llm_analytics',
            'github',
            'linear',
            'zendesk',
            'conversations',
            'error_tracking',
            'pganalyze',
        ])
        .describe(
            '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze'
        ),
    source_type: zod
        .enum([
            'session_analysis_cluster',
            'evaluation',
            'issue',
            'ticket',
            'issue_created',
            'issue_reopened',
            'issue_spiking',
        ])
        .describe(
            '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation` - Evaluation\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking'
        ),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
})

export const SignalsSourceConfigsPartialUpdateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum([
            'session_replay',
            'llm_analytics',
            'github',
            'linear',
            'zendesk',
            'conversations',
            'error_tracking',
            'pganalyze',
        ])
        .optional()
        .describe(
            '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze'
        ),
    source_type: zod
        .enum([
            'session_analysis_cluster',
            'evaluation',
            'issue',
            'ticket',
            'issue_created',
            'issue_reopened',
            'issue_spiking',
        ])
        .optional()
        .describe(
            '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation` - Evaluation\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking'
        ),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
})

/**
 * Per-user signal autonomy config (singleton keyed by user).

GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
POST   /api/users/<id>/signal_autonomy/ → create or update
DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
 */
export const UsersSignalAutonomyCreateBody = /* @__PURE__ */ zod.object({
    autostart_priority: zod
        .union([
            zod
                .enum(['P0', 'P1', 'P2', 'P3', 'P4'])
                .describe('\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
})
