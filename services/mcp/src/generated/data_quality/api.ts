/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 11 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create a check on this table or view, or refine the one already carrying the same fingerprint. Re-creating a semantically identical check returns 200 and the existing row, never a duplicate.
 */
export const WarehouseSavedQueriesChecksCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    saved_query_id: zod.string(),
})

export const warehouseSavedQueriesChecksCreateBodyNameMax = 128

export const warehouseSavedQueriesChecksCreateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const warehouseSavedQueriesChecksCreateBodyColumnNameMax = 400

export const warehouseSavedQueriesChecksCreateBodyAiModelMax = 128

export const warehouseSavedQueriesChecksCreateBodyConfidenceMin = 0
export const warehouseSavedQueriesChecksCreateBodyConfidenceMax = 1

export const WarehouseSavedQueriesChecksCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesChecksCreateBodyNameMax)
            .regex(warehouseSavedQueriesChecksCreateBodyNameRegExp)
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        column_name: zod
            .string()
            .max(warehouseSavedQueriesChecksCreateBodyColumnNameMax)
            .optional()
            .describe('Column the check applies to. Omit for table-scoped types like row_count.'),
        check_type: zod
            .enum(['not_null', 'unique', 'accepted_values', 'relationships', 'row_count', 'freshness', 'custom_sql'])
            .describe(
                '\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            )
            .describe(
                'Which assertion to make. Determines the shape of config; see \/check_types\/.\n\n\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            ),
        config: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe("Type-specific configuration, validated against the check type's JSON schema."),
        severity: zod
            .enum(['error', 'warn'])
            .describe('\* `error` - error\n\* `warn` - warn')
            .optional()
            .describe(
                "'error' failures mark the subject failing and notify; 'warn' failures only surface.\n\n\* `error` - error\n\* `warn` - warn"
            ),
        enabled: zod.boolean().optional().describe('Disabled checks are never run by any trigger.'),
        tags: zod.array(zod.string()).optional().describe('Free-form string labels for grouping and filtering.'),
        created_source: zod
            .enum(['user', 'ai_generated'])
            .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
            .optional()
            .describe(
                "Whether a human ('user') or an agent ('ai_generated') authored this check.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
            ),
        ai_model: zod
            .string()
            .max(warehouseSavedQueriesChecksCreateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(warehouseSavedQueriesChecksCreateBodyConfidenceMin)
            .max(warehouseSavedQueriesChecksCreateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe('The subject is implied by the URL (the parent saved query or table), never part of the body.')

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The table or view it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
 */
export const WarehouseSavedQueriesChecksPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality check.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    saved_query_id: zod.string(),
})

export const warehouseSavedQueriesChecksPartialUpdateBodyNameMax = 128

export const warehouseSavedQueriesChecksPartialUpdateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const warehouseSavedQueriesChecksPartialUpdateBodyColumnNameMax = 400

export const warehouseSavedQueriesChecksPartialUpdateBodyAiModelMax = 128

export const warehouseSavedQueriesChecksPartialUpdateBodyConfidenceMin = 0
export const warehouseSavedQueriesChecksPartialUpdateBodyConfidenceMax = 1

export const WarehouseSavedQueriesChecksPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesChecksPartialUpdateBodyNameMax)
            .regex(warehouseSavedQueriesChecksPartialUpdateBodyNameRegExp)
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        column_name: zod
            .string()
            .max(warehouseSavedQueriesChecksPartialUpdateBodyColumnNameMax)
            .optional()
            .describe('Column the check applies to. Omit for table-scoped types like row_count.'),
        check_type: zod
            .enum(['not_null', 'unique', 'accepted_values', 'relationships', 'row_count', 'freshness', 'custom_sql'])
            .describe(
                '\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            )
            .optional()
            .describe(
                'Which assertion to make. Determines the shape of config; see \/check_types\/.\n\n\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            ),
        config: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe("Type-specific configuration, validated against the check type's JSON schema."),
        severity: zod
            .enum(['error', 'warn'])
            .describe('\* `error` - error\n\* `warn` - warn')
            .optional()
            .describe(
                "'error' failures mark the subject failing and notify; 'warn' failures only surface.\n\n\* `error` - error\n\* `warn` - warn"
            ),
        enabled: zod.boolean().optional().describe('Disabled checks are never run by any trigger.'),
        tags: zod.array(zod.string()).optional().describe('Free-form string labels for grouping and filtering.'),
        created_source: zod
            .enum(['user', 'ai_generated'])
            .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
            .optional()
            .describe(
                "Whether a human ('user') or an agent ('ai_generated') authored this check.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
            ),
        ai_model: zod
            .string()
            .max(warehouseSavedQueriesChecksPartialUpdateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(warehouseSavedQueriesChecksPartialUpdateBodyConfidenceMin)
            .max(warehouseSavedQueriesChecksPartialUpdateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe('The subject is implied by the URL (the parent saved query or table), never part of the body.')

/**
 * CRUD for one subject's checks, plus the actions that run them and report on them.
 */
export const WarehouseSavedQueriesChecksDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality check.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    saved_query_id: zod.string(),
})

/**
 * Run this check now. Returns the suite run to poll for the report.
 */
export const WarehouseSavedQueriesChecksRunCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality check.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    saved_query_id: zod.string(),
})

/**
 * Recent run history for this check, newest first.
 */
export const WarehouseSavedQueriesChecksRunsListParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality check.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    saved_query_id: zod.string(),
})

/**
 * The check types this project can author, with the JSON schema of each type's config.
 */
export const WarehouseSavedQueriesChecksCheckTypesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    saved_query_id: zod.string(),
})

/**
 * Create a check on this table or view, or refine the one already carrying the same fingerprint. Re-creating a semantically identical check returns 200 and the existing row, never a duplicate.
 */
export const WarehouseTablesChecksCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    table_id: zod.string(),
})

export const warehouseTablesChecksCreateBodyNameMax = 128

export const warehouseTablesChecksCreateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const warehouseTablesChecksCreateBodyColumnNameMax = 400

export const warehouseTablesChecksCreateBodyAiModelMax = 128

export const warehouseTablesChecksCreateBodyConfidenceMin = 0
export const warehouseTablesChecksCreateBodyConfidenceMax = 1

export const WarehouseTablesChecksCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseTablesChecksCreateBodyNameMax)
            .regex(warehouseTablesChecksCreateBodyNameRegExp)
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        column_name: zod
            .string()
            .max(warehouseTablesChecksCreateBodyColumnNameMax)
            .optional()
            .describe('Column the check applies to. Omit for table-scoped types like row_count.'),
        check_type: zod
            .enum(['not_null', 'unique', 'accepted_values', 'relationships', 'row_count', 'freshness', 'custom_sql'])
            .describe(
                '\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            )
            .describe(
                'Which assertion to make. Determines the shape of config; see \/check_types\/.\n\n\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            ),
        config: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe("Type-specific configuration, validated against the check type's JSON schema."),
        severity: zod
            .enum(['error', 'warn'])
            .describe('\* `error` - error\n\* `warn` - warn')
            .optional()
            .describe(
                "'error' failures mark the subject failing and notify; 'warn' failures only surface.\n\n\* `error` - error\n\* `warn` - warn"
            ),
        enabled: zod.boolean().optional().describe('Disabled checks are never run by any trigger.'),
        tags: zod.array(zod.string()).optional().describe('Free-form string labels for grouping and filtering.'),
        created_source: zod
            .enum(['user', 'ai_generated'])
            .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
            .optional()
            .describe(
                "Whether a human ('user') or an agent ('ai_generated') authored this check.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
            ),
        ai_model: zod
            .string()
            .max(warehouseTablesChecksCreateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(warehouseTablesChecksCreateBodyConfidenceMin)
            .max(warehouseTablesChecksCreateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe('The subject is implied by the URL (the parent saved query or table), never part of the body.')

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The table or view it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
 */
export const WarehouseTablesChecksPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality check.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    table_id: zod.string(),
})

export const warehouseTablesChecksPartialUpdateBodyNameMax = 128

export const warehouseTablesChecksPartialUpdateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const warehouseTablesChecksPartialUpdateBodyColumnNameMax = 400

export const warehouseTablesChecksPartialUpdateBodyAiModelMax = 128

export const warehouseTablesChecksPartialUpdateBodyConfidenceMin = 0
export const warehouseTablesChecksPartialUpdateBodyConfidenceMax = 1

export const WarehouseTablesChecksPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseTablesChecksPartialUpdateBodyNameMax)
            .regex(warehouseTablesChecksPartialUpdateBodyNameRegExp)
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        column_name: zod
            .string()
            .max(warehouseTablesChecksPartialUpdateBodyColumnNameMax)
            .optional()
            .describe('Column the check applies to. Omit for table-scoped types like row_count.'),
        check_type: zod
            .enum(['not_null', 'unique', 'accepted_values', 'relationships', 'row_count', 'freshness', 'custom_sql'])
            .describe(
                '\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            )
            .optional()
            .describe(
                'Which assertion to make. Determines the shape of config; see \/check_types\/.\n\n\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            ),
        config: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe("Type-specific configuration, validated against the check type's JSON schema."),
        severity: zod
            .enum(['error', 'warn'])
            .describe('\* `error` - error\n\* `warn` - warn')
            .optional()
            .describe(
                "'error' failures mark the subject failing and notify; 'warn' failures only surface.\n\n\* `error` - error\n\* `warn` - warn"
            ),
        enabled: zod.boolean().optional().describe('Disabled checks are never run by any trigger.'),
        tags: zod.array(zod.string()).optional().describe('Free-form string labels for grouping and filtering.'),
        created_source: zod
            .enum(['user', 'ai_generated'])
            .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
            .optional()
            .describe(
                "Whether a human ('user') or an agent ('ai_generated') authored this check.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
            ),
        ai_model: zod
            .string()
            .max(warehouseTablesChecksPartialUpdateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(warehouseTablesChecksPartialUpdateBodyConfidenceMin)
            .max(warehouseTablesChecksPartialUpdateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe('The subject is implied by the URL (the parent saved query or table), never part of the body.')

/**
 * CRUD for one subject's checks, plus the actions that run them and report on them.
 */
export const WarehouseTablesChecksDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality check.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    table_id: zod.string(),
})

/**
 * Run this check now. Returns the suite run to poll for the report.
 */
export const WarehouseTablesChecksRunCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality check.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    table_id: zod.string(),
})

/**
 * Recent run history for this check, newest first.
 */
export const WarehouseTablesChecksRunsListParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality check.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    table_id: zod.string(),
})
