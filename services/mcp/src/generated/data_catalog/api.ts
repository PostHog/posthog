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
 * Trust marks on warehouse tables and views. Reads exclude soft-deleted targets.
 */
export const DataCatalogCertificationsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DataCatalogCertificationsCreateBody = /* @__PURE__ */ zod
    .object({
        table_id: zod.string().optional().describe('Warehouse table id to certify (XOR the other targets).'),
        saved_query_id: zod.string().optional().describe('Warehouse view (saved query) id to certify.'),
        table_name: zod.string().optional().describe('Table name; 409 with candidates if ambiguous.'),
        view_name: zod.string().optional().describe('View name; 409 with candidates if ambiguous.'),
        notes: zod.string().optional().describe('Why this mark exists.'),
    })
    .describe('Input for proposing a certification: address the target by id or (convenience) by name.')

/**
 * Mark the target as certified (prefer this source).
 */
export const DataCatalogCertificationsCertifyCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this table certification.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Mark the target as deprecated (avoid this source).
 */
export const DataCatalogCertificationsDeprecateCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this table certification.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create a metric, or refine the one already holding this name for the team.
 */
export const DataCatalogMetricsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const dataCatalogMetricsCreateBodyNameMax = 128

export const dataCatalogMetricsCreateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]*$')
export const dataCatalogMetricsCreateBodyDisplayNameMax = 255

export const dataCatalogMetricsCreateBodyUnitMax = 64

export const dataCatalogMetricsCreateBodySourceInsightShortIdMax = 12

export const dataCatalogMetricsCreateBodyAiModelMax = 128

export const dataCatalogMetricsCreateBodyConfidenceMin = 0
export const dataCatalogMetricsCreateBodyConfidenceMax = 1

export const DataCatalogMetricsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(dataCatalogMetricsCreateBodyNameMax)
        .regex(dataCatalogMetricsCreateBodyNameRegExp)
        .describe('Identifier-safe run handle, unique per team and reserved forever. Write-once.'),
    display_name: zod
        .string()
        .max(dataCatalogMetricsCreateBodyDisplayNameMax)
        .optional()
        .describe('Human-friendly label. Mutable, unlike name.'),
    description: zod.string().describe('What the metric means and how to interpret it.'),
    unit: zod
        .string()
        .max(dataCatalogMetricsCreateBodyUnitMax)
        .optional()
        .describe('Unit of the result, e.g. usd, percent, cents.'),
    definition: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.'),
    source_insight_short_id: zod
        .string()
        .max(dataCatalogMetricsCreateBodySourceInsightShortIdMax)
        .nullish()
        .describe(
            "Create the metric from this insight's query (snapshotted server-side). Set to null to unlink. Mutually exclusive with definition."
        ),
    ai_model: zod
        .string()
        .max(dataCatalogMetricsCreateBodyAiModelMax)
        .optional()
        .describe('Model that generated the metric, if AI-authored.'),
    confidence: zod
        .number()
        .min(dataCatalogMetricsCreateBodyConfidenceMin)
        .max(dataCatalogMetricsCreateBodyConfidenceMax)
        .nullish()
        .describe("AI author's confidence in the proposal, 0-1."),
    reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
})

/**
 * CRUD for catalog metrics, addressed by their reserved ``name`` (e.g. /metrics/mrr/).
 */
export const DataCatalogMetricsPartialUpdateParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const dataCatalogMetricsPartialUpdateBodyNameMax = 128

export const dataCatalogMetricsPartialUpdateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]*$')
export const dataCatalogMetricsPartialUpdateBodyDisplayNameMax = 255

export const dataCatalogMetricsPartialUpdateBodyUnitMax = 64

export const dataCatalogMetricsPartialUpdateBodySourceInsightShortIdMax = 12

export const dataCatalogMetricsPartialUpdateBodyAiModelMax = 128

export const dataCatalogMetricsPartialUpdateBodyConfidenceMin = 0
export const dataCatalogMetricsPartialUpdateBodyConfidenceMax = 1

export const DataCatalogMetricsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(dataCatalogMetricsPartialUpdateBodyNameMax)
        .regex(dataCatalogMetricsPartialUpdateBodyNameRegExp)
        .optional()
        .describe('Identifier-safe run handle, unique per team and reserved forever. Write-once.'),
    display_name: zod
        .string()
        .max(dataCatalogMetricsPartialUpdateBodyDisplayNameMax)
        .optional()
        .describe('Human-friendly label. Mutable, unlike name.'),
    description: zod.string().optional().describe('What the metric means and how to interpret it.'),
    unit: zod
        .string()
        .max(dataCatalogMetricsPartialUpdateBodyUnitMax)
        .optional()
        .describe('Unit of the result, e.g. usd, percent, cents.'),
    definition: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.'),
    source_insight_short_id: zod
        .string()
        .max(dataCatalogMetricsPartialUpdateBodySourceInsightShortIdMax)
        .nullish()
        .describe(
            "Create the metric from this insight's query (snapshotted server-side). Set to null to unlink. Mutually exclusive with definition."
        ),
    ai_model: zod
        .string()
        .max(dataCatalogMetricsPartialUpdateBodyAiModelMax)
        .optional()
        .describe('Model that generated the metric, if AI-authored.'),
    confidence: zod
        .number()
        .min(dataCatalogMetricsPartialUpdateBodyConfidenceMin)
        .max(dataCatalogMetricsPartialUpdateBodyConfidenceMax)
        .nullish()
        .describe("AI author's confidence in the proposal, 0-1."),
    reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
})

/**
 * Bless a metric as canonical. Returns 409 while the metric is drifted from its insight.
 */
export const DataCatalogMetricsApproveCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Execute the metric's definition and return the normalized result envelope.
 */
export const DataCatalogMetricsRunCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DataCatalogMetricsRunCreateQueryParams = /* @__PURE__ */ zod.object({
    refresh: zod
        .enum(['blocking', 'async', 'lazy_async', 'force_blocking', 'force_async', 'force_cache'])
        .optional()
        .describe(
            'Cache/execution behavior, same semantics as /query/. Omit to serve a fresh cache hit and calculate blocking when stale.\n\n* `blocking` - blocking\n* `async` - async\n* `lazy_async` - lazy_async\n* `force_blocking` - force_blocking\n* `force_async` - force_async\n* `force_cache` - force_cache'
        ),
})

export const DataCatalogMetricsRunCreateBody = /* @__PURE__ */ zod
    .object({
        date_from: zod
            .string()
            .optional()
            .describe(
                "Override the start of the query window (e.g. '-7d'). Rejected for HogQLQuery metrics, whose window is fixed in SQL."
            ),
        date_to: zod.string().optional().describe('Override the end of the query window.'),
        interval: zod
            .enum(['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'])
            .describe(
                '* `second` - second\n* `minute` - minute\n* `hour` - hour\n* `day` - day\n* `week` - week\n* `month` - month\n* `quarter` - quarter\n* `year` - year'
            )
            .optional()
            .describe(
                'Override the bucket interval. Rejected for HogQLQuery metrics.\n\n* `second` - second\n* `minute` - minute\n* `hour` - hour\n* `day` - day\n* `week` - week\n* `month` - month\n* `quarter` - quarter\n* `year` - year'
            ),
        query_id: zod.string().optional().describe('Client-supplied id to correlate or cancel the run.'),
    })
    .describe('Optional run-time overrides. The whole body may be omitted; a metric runs by its URL name.')

/**
 * Reviewed join facts. Accepting one promotes it to a real DataWarehouseJoin; rejections persist.
 */
export const DataCatalogRelationshipProposalsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const dataCatalogRelationshipProposalsCreateBodySourceTableNameMax = 400

export const dataCatalogRelationshipProposalsCreateBodySourceTableKeyMax = 400

export const dataCatalogRelationshipProposalsCreateBodyJoiningTableNameMax = 400

export const dataCatalogRelationshipProposalsCreateBodyJoiningTableKeyMax = 400

export const dataCatalogRelationshipProposalsCreateBodyFieldNameMax = 400

export const dataCatalogRelationshipProposalsCreateBodyConfidenceMin = 0
export const dataCatalogRelationshipProposalsCreateBodyConfidenceMax = 1

export const DataCatalogRelationshipProposalsCreateBody = /* @__PURE__ */ zod.object({
    source_table_name: zod
        .string()
        .max(dataCatalogRelationshipProposalsCreateBodySourceTableNameMax)
        .describe('Name of the table the join starts from.'),
    source_table_key: zod
        .string()
        .max(dataCatalogRelationshipProposalsCreateBodySourceTableKeyMax)
        .describe('HogQL key expression on the source table (casts allowed).'),
    joining_table_name: zod
        .string()
        .max(dataCatalogRelationshipProposalsCreateBodyJoiningTableNameMax)
        .describe('Name of the table being joined in.'),
    joining_table_key: zod
        .string()
        .max(dataCatalogRelationshipProposalsCreateBodyJoiningTableKeyMax)
        .describe('HogQL key expression on the joining table (casts allowed).'),
    field_name: zod
        .string()
        .max(dataCatalogRelationshipProposalsCreateBodyFieldNameMax)
        .describe('Accessor the join adds to the source table.'),
    configuration: zod.unknown().optional().describe('Extra join configuration, e.g. a field mapping.'),
    confidence: zod
        .number()
        .min(dataCatalogRelationshipProposalsCreateBodyConfidenceMin)
        .max(dataCatalogRelationshipProposalsCreateBodyConfidenceMax)
        .nullish()
        .describe('Discovery confidence in this join, 0-1.'),
    reasoning: zod.string().optional().describe('Why this join is proposed.'),
    evidence: zod.unknown().optional().describe('Sampling evidence: match rates, sample values.'),
})

/**
 * Promote the proposal to a real warehouse join after re-validating and probing it.
 */
export const DataCatalogRelationshipProposalsAcceptCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this relationship proposal.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Reject the proposal. Persists forever so the pair is never re-proposed.
 */
export const DataCatalogRelationshipProposalsRejectCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this relationship proposal.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DataCatalogRelationshipProposalsRejectCreateBody = /* @__PURE__ */ zod.object({
    rejection_reason: zod
        .string()
        .optional()
        .describe('Why the proposal is rejected. Persisted so it is never re-proposed.'),
})
