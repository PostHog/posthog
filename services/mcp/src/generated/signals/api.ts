/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 10 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Return `SignalScratchpad` entries for this project. ILIKE matches on `content`; tags filter via Postgres array overlap. Expired `agent_inference` entries are hidden by default.
 * @summary Search durable memories
 */
export const SignalsScoutMemoryListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsScoutScratchpadListQueryLimitMax = 100

export const SignalsScoutMemoryListQueryParams = /* @__PURE__ */ zod.object({
    include_expired: zod
        .boolean()
        .optional()
        .describe('Include expired `agent_inference` entries (default false). Use for audit/debug only.'),
    limit: zod
        .number()
        .min(1)
        .max(signalsScoutScratchpadListQueryLimitMax)
        .optional()
        .describe('Max rows to return (default 20, hard cap 100).'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    tags: zod
        .array(zod.string())
        .optional()
        .describe('Tags filtered via Postgres array overlap. Pass repeated `tags=` query params to filter.'),
    text: zod
        .string()
        .optional()
        .describe('ILIKE substring match against `content`. Omit to return the most recent entries.'),
})

/**
 * Upsert an `agent_inference` memory keyed on `(team, key)`. Re-using a key updates the existing entry in place and resets its TTL. Cannot overwrite `human_confirmed` entries.
 * @summary Write or refresh an agent memory
 */
export const SignalsScoutMemoryCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsScoutScratchpadCreateBodyKeyMax = 300

export const signalsScoutScratchpadCreateBodyTtlDaysMax = 90

export const SignalsScoutMemoryCreateBody = /* @__PURE__ */ zod
    .object({
        key: zod
            .string()
            .max(signalsScoutScratchpadCreateBodyKeyMax)
            .describe('Agent-chosen semantic key. Re-using a key updates the existing entry in place.'),
        content: zod.string().describe('Prose to write. Read verbatim into future prompts.'),
        tags: zod.array(zod.string()).optional().describe('Tags for later search. Empty/whitespace tags are dropped.'),
        ttl_days: zod
            .number()
            .min(1)
            .max(signalsScoutScratchpadCreateBodyTtlDaysMax)
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
export const SignalsScoutMemoryDeleteParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsScoutScratchpadDeleteBodyKeyMax = 300

export const SignalsScoutMemoryDeleteBody = /* @__PURE__ */ zod
    .object({
        key: zod.string().max(signalsScoutScratchpadDeleteBodyKeyMax).describe('Memory key to delete.'),
    })
    .describe('Request body for `forget`. Only `agent_inference` keys can be deleted.')

/**
 * Return the most recent `SignalScoutRun` summaries for this project, newest first. Used by the headless agent to dedupe against work other runs already covered. ILIKE matches on `summary`; results are capped at 100.
 * @summary Search recent agent runs
 */
export const SignalsScoutRunsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsScoutRunsListQueryLimitMax = 100

export const SignalsScoutRunsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod
        .number()
        .min(1)
        .max(signalsScoutRunsListQueryLimitMax)
        .optional()
        .describe('Max rows to return (default 20, hard cap 100).'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    since: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('ISO-8601 lower bound on `started_at`. Use to scope to a recent window.'),
    text: zod
        .string()
        .optional()
        .describe('ILIKE substring match against `summary`. Omit to return the latest runs unfiltered.'),
})

/**
 * Return the full `SignalScoutRun` row including `summary`, `findings`, `hypotheses_considered`, `run_metrics`, and `metadata`. Strictly team-scoped — a UUID belonging to another team returns 404.
 * @summary Get a run by ID
 */
export const signalsScoutRunsRetrievePathIdRegExp = new RegExp('^[0-9a-f-]+$')

export const SignalsScoutRunsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().regex(signalsScoutRunsRetrievePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Persist a finding to `SignalScoutRun.findings` and fire `emit_signal` with `source_product = signals_scout`. Idempotent on `(run_id, finding_id)` — a second call with the same `finding_id` short-circuits without re-firing the pipeline. Honors the team's `shadow_mode` flag: when true, the finding is persisted but the external emit is a no-op.
 * @summary Emit a finding for a run
 */
export const signalsScoutRunsFindingsCreatePathIdRegExp = new RegExp('^[0-9a-f-]+$')

export const SignalsScoutRunsFindingsCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().regex(signalsScoutRunsFindingsCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsScoutRunsFindingsCreateBodyWeightMin = 0
export const signalsScoutRunsFindingsCreateBodyWeightMax = 1

export const signalsScoutRunsFindingsCreateBodyConfidenceMin = 0
export const signalsScoutRunsFindingsCreateBodyConfidenceMax = 1

export const signalsScoutRunsFindingsCreateBodyEvidenceMax = 20

export const SignalsScoutRunsFindingsCreateBody = /* @__PURE__ */ zod
    .object({
        description: zod.string().describe("Canonical evidence-bundle prose. Becomes the signal's `description`."),
        weight: zod
            .number()
            .min(signalsScoutRunsFindingsCreateBodyWeightMin)
            .max(signalsScoutRunsFindingsCreateBodyWeightMax)
            .describe("Agent's weight for the signal in [0, 1]. Drives ranking in the inbox."),
        confidence: zod
            .number()
            .min(signalsScoutRunsFindingsCreateBodyConfidenceMin)
            .max(signalsScoutRunsFindingsCreateBodyConfidenceMax)
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
                    .describe('One citation attached to a finding. Mirrors `SignalsScoutEvidenceEntry`.')
            )
            .max(signalsScoutRunsFindingsCreateBodyEvidenceMax)
            .describe('Citations supporting the finding. Capped at 20 entries.'),
        hypothesis: zod.string().nullish().describe('Optional one-line hypothesis the finding tests.'),
        severity: zod.string().nullish().describe('Optional severity tag (`P0`-`P4`) — informational only.'),
        dedupe_keys: zod
            .array(zod.string())
            .optional()
            .describe('Optional keys for downstream dedupe (e.g. `error_tracking_issue:<id>`).'),
        time_range: zod
            .union([
                zod.object({
                    date_from: zod.string().describe("ISO-8601 inclusive lower bound for the finding's window."),
                    date_to: zod.string().describe("ISO-8601 inclusive upper bound for the finding's window."),
                }),
                zod.null(),
            ])
            .optional()
            .describe('Optional time window the finding refers to.'),
        mcp_trace_id: zod.string().nullish().describe('Optional MCP trace id for cross-system debugging.'),
        finding_id: zod
            .string()
            .nullish()
            .describe('Idempotency key. Re-using the same id within a run short-circuits without re-emitting.'),
    })
    .describe('Request body for `emit-finding`. Run attribution is taken from the URL path.')

export const SignalsReportsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SignalsReportsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    ordering: zod
        .string()
        .optional()
        .describe(
            "Comma-separated ordering clauses. Each clause is a field name optionally prefixed with '-' for descending. Allowed fields: status, is_suggested_reviewer, signal_count, total_weight, priority, created_at, updated_at, id. Defaults to '-is_suggested_reviewer,status,-updated_at'."
        ),
    search: zod.string().optional().describe('Case-insensitive substring match against report title and summary.'),
    source_product: zod
        .string()
        .optional()
        .describe(
            'Comma-separated list of source products to include. Reports are kept if at least one of their contributing signals comes from one of these products (e.g. error_tracking, session_replay).'
        ),
    status: zod
        .string()
        .optional()
        .describe(
            'Comma-separated list of statuses to include. Valid values: potential, candidate, in_progress, pending_input, ready, failed, suppressed. Defaults to all statuses except suppressed.'
        ),
    suggested_reviewers: zod
        .string()
        .optional()
        .describe(
            'Comma-separated list of PostHog user UUIDs. Reports are kept if their suggested reviewers include any of the given users.'
        ),
})

export const SignalsReportsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this signal report.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SignalsSourceConfigsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SignalsSourceConfigsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const SignalsSourceConfigsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this signal source config.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
