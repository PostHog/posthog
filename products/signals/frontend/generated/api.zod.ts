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
 * Upsert an `agent_inference` memory keyed on `(team, key)`. Re-using a key updates the existing entry in place and resets its TTL. Cannot overwrite `human_confirmed` entries.
 * @summary Write or refresh an agent memory
 */
export const signalsAgentMemoryCreateBodyKeyMax = 300

export const signalsAgentMemoryCreateBodyTtlDaysMax = 90

export const SignalsAgentMemoryCreateBody = /* @__PURE__ */ zod
    .object({
        key: zod
            .string()
            .max(signalsAgentMemoryCreateBodyKeyMax)
            .describe('Agent-chosen semantic key. Re-using a key updates the existing entry in place.'),
        content: zod.string().describe('Prose to write. Read verbatim into future prompts.'),
        tags: zod.array(zod.string()).optional().describe('Tags for later search. Empty/whitespace tags are dropped.'),
        ttl_days: zod
            .number()
            .min(1)
            .max(signalsAgentMemoryCreateBodyTtlDaysMax)
            .optional()
            .describe('Days until expiry (default 7, hard cap 90).'),
        run_id: zod
            .uuid()
            .nullish()
            .describe(
                'Run that authored this memory; persisted as `created_by_run_id` for lineage. Must reference a run on this same project — cross-project run UUIDs are rejected.'
            ),
    })
    .describe('Request body for `remember`. Authority is always `agent_inference` — humans use Django admin.')

/**
 * Delete an `agent_inference` entry by key. Returns `deleted=false` if no row matched. Cannot delete `human_confirmed` entries — those are human-managed only.
 * @summary Delete an agent memory by key
 */
export const signalsAgentMemoryDeleteBodyKeyMax = 300

export const SignalsAgentMemoryDeleteBody = /* @__PURE__ */ zod
    .object({
        key: zod.string().max(signalsAgentMemoryDeleteBodyKeyMax).describe('Memory key to delete.'),
    })
    .describe('Request body for `forget`. Only `agent_inference` keys can be deleted.')

/**
 * Persist a finding to `SignalAgentRun.findings` and fire `emit_signal` with `source_product = signals_agent`. Idempotent on `(run_id, finding_id)` — a second call with the same `finding_id` short-circuits without re-firing the pipeline. Honors the team's `shadow_mode` flag: when true, the finding is persisted but the external emit is a no-op.
 * @summary Emit a finding for a run
 */
export const signalsAgentRunsFindingsCreateBodyWeightMin = 0
export const signalsAgentRunsFindingsCreateBodyWeightMax = 1

export const signalsAgentRunsFindingsCreateBodyConfidenceMin = 0
export const signalsAgentRunsFindingsCreateBodyConfidenceMax = 1

export const signalsAgentRunsFindingsCreateBodyEvidenceMax = 20

export const SignalsAgentRunsFindingsCreateBody = /* @__PURE__ */ zod
    .object({
        description: zod.string().describe("Canonical evidence-bundle prose. Becomes the signal's `description`."),
        weight: zod
            .number()
            .min(signalsAgentRunsFindingsCreateBodyWeightMin)
            .max(signalsAgentRunsFindingsCreateBodyWeightMax)
            .describe("Agent's weight for the signal in [0, 1]. Drives ranking in the inbox."),
        confidence: zod
            .number()
            .min(signalsAgentRunsFindingsCreateBodyConfidenceMin)
            .max(signalsAgentRunsFindingsCreateBodyConfidenceMax)
            .describe("Agent's confidence the finding is real in [0, 1]. Persisted in `extra`."),
        evidence: zod
            .array(
                zod
                    .object({
                        source_product: zod
                            .string()
                            .describe(
                                'Source the citation came from (`error_tracking`, `session_replay`, `logs`, ...).'
                            ),
                        summary: zod
                            .string()
                            .describe('One-sentence prose about why this evidence supports the finding.'),
                        entity_id: zod
                            .string()
                            .nullish()
                            .describe('Optional ID of the cited entity (issue id, recording id, log query id).'),
                    })
                    .describe('One citation attached to a finding. Mirrors `SignalsAgentEvidenceEntry`.')
            )
            .max(signalsAgentRunsFindingsCreateBodyEvidenceMax)
            .describe('Citations supporting the finding. Capped at 20 entries.'),
        hypothesis: zod.string().nullish().describe('Optional one-line hypothesis the finding tests.'),
        severity: zod.string().nullish().describe('Optional severity tag (`P0`-`P4`) — informational only.'),
        dedupe_keys: zod
            .array(zod.string())
            .optional()
            .describe('Optional keys for downstream dedupe (e.g. `error_tracking_issue:<id>`).'),
        time_range: zod
            .object({
                date_from: zod.string().describe("ISO-8601 inclusive lower bound for the finding's window."),
                date_to: zod.string().describe("ISO-8601 inclusive upper bound for the finding's window."),
            })
            .nullish()
            .describe('Optional time window the finding refers to.'),
        mcp_trace_id: zod.string().nullish().describe('Optional MCP trace id for cross-system debugging.'),
        finding_id: zod
            .string()
            .nullish()
            .describe('Idempotency key. Re-using the same id within a run short-circuits without re-emitting.'),
    })
    .describe('Request body for `emit-finding`. Run attribution is taken from the URL path.')

/**
 * View and control signal processing pipeline state for a team.
 */
export const SignalsProcessingPauseUpdateBody = /* @__PURE__ */ zod.object({
    timestamp: zod.iso.datetime({}).describe('Pause the grouping pipeline until this timestamp (ISO 8601).'),
})

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
            'signals_agent',
        ])
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `conversations` - Conversations\n* `error_tracking` - Error tracking\n* `signals_agent` - Signals agent'
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
            'cross_source_issue',
        ])
        .describe(
            '* `session_analysis_cluster` - Session analysis cluster\n* `evaluation` - Evaluation\n* `issue` - Issue\n* `ticket` - Ticket\n* `issue_created` - Issue created\n* `issue_reopened` - Issue reopened\n* `issue_spiking` - Issue spiking\n* `cross_source_issue` - Cross source issue'
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
            'signals_agent',
        ])
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `conversations` - Conversations\n* `error_tracking` - Error tracking\n* `signals_agent` - Signals agent'
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
            'cross_source_issue',
        ])
        .describe(
            '* `session_analysis_cluster` - Session analysis cluster\n* `evaluation` - Evaluation\n* `issue` - Issue\n* `ticket` - Ticket\n* `issue_created` - Issue created\n* `issue_reopened` - Issue reopened\n* `issue_spiking` - Issue spiking\n* `cross_source_issue` - Cross source issue'
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
            'signals_agent',
        ])
        .optional()
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `conversations` - Conversations\n* `error_tracking` - Error tracking\n* `signals_agent` - Signals agent'
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
            'cross_source_issue',
        ])
        .optional()
        .describe(
            '* `session_analysis_cluster` - Session analysis cluster\n* `evaluation` - Evaluation\n* `issue` - Issue\n* `ticket` - Ticket\n* `issue_created` - Issue created\n* `issue_reopened` - Issue reopened\n* `issue_spiking` - Issue spiking\n* `cross_source_issue` - Cross source issue'
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
