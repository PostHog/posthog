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
    timestamp: zod.iso.datetime({}).describe('Pause the grouping pipeline until this timestamp (ISO 8601).'),
})

export const SignalsSourceConfigsCreateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum(['session_replay', 'llm_analytics', 'github', 'linear', 'zendesk', 'conversations', 'error_tracking'])
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `conversations` - Conversations\n* `error_tracking` - Error tracking'
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
            '* `session_analysis_cluster` - Session analysis cluster\n* `evaluation` - Evaluation\n* `issue` - Issue\n* `ticket` - Ticket\n* `issue_created` - Issue created\n* `issue_reopened` - Issue reopened\n* `issue_spiking` - Issue spiking'
        ),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
})

export const SignalsSourceConfigsUpdateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum(['session_replay', 'llm_analytics', 'github', 'linear', 'zendesk', 'conversations', 'error_tracking'])
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `conversations` - Conversations\n* `error_tracking` - Error tracking'
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
            '* `session_analysis_cluster` - Session analysis cluster\n* `evaluation` - Evaluation\n* `issue` - Issue\n* `ticket` - Ticket\n* `issue_created` - Issue created\n* `issue_reopened` - Issue reopened\n* `issue_spiking` - Issue spiking'
        ),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
})

export const SignalsSourceConfigsPartialUpdateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum(['session_replay', 'llm_analytics', 'github', 'linear', 'zendesk', 'conversations', 'error_tracking'])
        .optional()
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `conversations` - Conversations\n* `error_tracking` - Error tracking'
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
            '* `session_analysis_cluster` - Session analysis cluster\n* `evaluation` - Evaluation\n* `issue` - Issue\n* `ticket` - Ticket\n* `issue_created` - Issue created\n* `issue_reopened` - Issue reopened\n* `issue_spiking` - Issue spiking'
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
                .describe('* `P0` - P0\n* `P1` - P1\n* `P2` - P2\n* `P3` - P3\n* `P4` - P4'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
})
