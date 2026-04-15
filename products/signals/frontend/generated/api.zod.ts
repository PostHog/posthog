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
 * Return current processing state including pause status.
 */
export const SignalProcessingListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            paused_until: zod.iso
                .datetime({})
                .nullable()
                .describe('The timestamp the pipeline is paused until, or null if not paused/not running.'),
        })
    ),
})

/**
 * View and control signal processing pipeline state for a team.
 */
export const SignalProcessingPauseUpdateBody = /* @__PURE__ */ zod.object({
    timestamp: zod.iso.datetime({}).describe('Pause the grouping pipeline until this timestamp (ISO 8601).'),
})

export const SignalProcessingPauseUpdateResponse = /* @__PURE__ */ zod.object({
    status: zod.string().describe("Always 'paused'."),
    paused_until: zod.iso.datetime({}).describe('The timestamp the pipeline is paused until.'),
})

/**
 * View and control signal processing pipeline state for a team.
 */
export const SignalProcessingUnpauseCreateResponse = /* @__PURE__ */ zod.object({
    status: zod.string().describe("Always 'unpaused'."),
    was_paused: zod.boolean().describe('Whether the workflow was actually paused at the time of the call.'),
})

export const SignalSourceConfigsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            source_product: zod
                .enum(['session_replay', 'llm_analytics', 'github', 'linear', 'zendesk', 'error_tracking'])
                .describe(
                    '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `error_tracking` - Error tracking'
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
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
            status: zod.string().nullable(),
        })
    ),
})

export const SignalSourceConfigsCreateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum(['session_replay', 'llm_analytics', 'github', 'linear', 'zendesk', 'error_tracking'])
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `error_tracking` - Error tracking'
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
