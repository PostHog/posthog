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
 * Read-only reports for batches of check executions.
 */
export const DataQualityCheckSuiteRunsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality suite run.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Every check execution in this suite run.
 */
export const DataQualityCheckSuiteRunsCheckRunsListParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality suite run.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create a check, or refine the one already carrying the same fingerprint. Re-creating a semantically identical check returns 200 and the existing row, never a duplicate.
 */
export const DataQualityChecksCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DataQualityChecksCreateQueryParams = /* @__PURE__ */ zod.object({
    check_type: zod.string().optional().describe('Filter the list to one check type.'),
    subject_type: zod.string().optional().describe("Filter the list to 'table' or 'view' subjects."),
    subject_uuid: zod.string().optional().describe('Filter the list to one table or view.'),
})

export const dataQualityChecksCreateBodyNameMax = 128

export const dataQualityChecksCreateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const dataQualityChecksCreateBodyColumnNameMax = 400

export const dataQualityChecksCreateBodyScheduleIntervalMinutesMin = -2147483648
export const dataQualityChecksCreateBodyScheduleIntervalMinutesMax = 2147483647

export const dataQualityChecksCreateBodyAiModelMax = 128

export const dataQualityChecksCreateBodyConfidenceMin = 0
export const dataQualityChecksCreateBodyConfidenceMax = 1

export const DataQualityChecksCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(dataQualityChecksCreateBodyNameMax)
        .regex(dataQualityChecksCreateBodyNameRegExp)
        .optional()
        .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
    description: zod.string().optional().describe('Why this check exists and what a failure means.'),
    subject_type: zod
        .enum(['table', 'view'])
        .describe('\* `table` - table\n\* `view` - view')
        .describe(
            "Kind of catalog object being checked: 'table' (a synced warehouse table) or 'view' (a saved query).\n\n\* `table` - table\n\* `view` - view"
        ),
    subject_uuid: zod.string().describe('Id of the table or view being checked.'),
    column_name: zod
        .string()
        .max(dataQualityChecksCreateBodyColumnNameMax)
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
    tags: zod.unknown().optional().describe('Free-form labels for grouping and filtering.'),
    run_on_materialization: zod
        .boolean()
        .optional()
        .describe('Run after the view materializes. Never delays or fails the materialization itself.'),
    schedule_interval_minutes: zod
        .number()
        .min(dataQualityChecksCreateBodyScheduleIntervalMinutesMin)
        .max(dataQualityChecksCreateBodyScheduleIntervalMinutesMax)
        .nullish()
        .describe('Independent cadence in minutes. Omit for no schedule of its own.'),
    created_source: zod
        .enum(['user', 'ai_generated'])
        .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
        .optional()
        .describe(
            "Whether a human ('user') or an agent ('ai_generated') authored this check.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
        ),
    ai_model: zod
        .string()
        .max(dataQualityChecksCreateBodyAiModelMax)
        .optional()
        .describe('Model that generated the check, if AI-authored.'),
    confidence: zod
        .number()
        .min(dataQualityChecksCreateBodyConfidenceMin)
        .max(dataQualityChecksCreateBodyConfidenceMax)
        .nullish()
        .describe("AI author's confidence in the check, 0-1."),
    reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
})

/**
 * CRUD for data quality checks, plus the actions that run them and report on them.
 */
export const DataQualityChecksPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality check.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const dataQualityChecksPartialUpdateBodyNameMax = 128

export const dataQualityChecksPartialUpdateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const dataQualityChecksPartialUpdateBodyColumnNameMax = 400

export const dataQualityChecksPartialUpdateBodyScheduleIntervalMinutesMin = -2147483648
export const dataQualityChecksPartialUpdateBodyScheduleIntervalMinutesMax = 2147483647

export const dataQualityChecksPartialUpdateBodyAiModelMax = 128

export const dataQualityChecksPartialUpdateBodyConfidenceMin = 0
export const dataQualityChecksPartialUpdateBodyConfidenceMax = 1

export const DataQualityChecksPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(dataQualityChecksPartialUpdateBodyNameMax)
        .regex(dataQualityChecksPartialUpdateBodyNameRegExp)
        .optional()
        .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
    description: zod.string().optional().describe('Why this check exists and what a failure means.'),
    subject_type: zod
        .enum(['table', 'view'])
        .describe('\* `table` - table\n\* `view` - view')
        .optional()
        .describe(
            "Kind of catalog object being checked: 'table' (a synced warehouse table) or 'view' (a saved query).\n\n\* `table` - table\n\* `view` - view"
        ),
    subject_uuid: zod.string().optional().describe('Id of the table or view being checked.'),
    column_name: zod
        .string()
        .max(dataQualityChecksPartialUpdateBodyColumnNameMax)
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
    tags: zod.unknown().optional().describe('Free-form labels for grouping and filtering.'),
    run_on_materialization: zod
        .boolean()
        .optional()
        .describe('Run after the view materializes. Never delays or fails the materialization itself.'),
    schedule_interval_minutes: zod
        .number()
        .min(dataQualityChecksPartialUpdateBodyScheduleIntervalMinutesMin)
        .max(dataQualityChecksPartialUpdateBodyScheduleIntervalMinutesMax)
        .nullish()
        .describe('Independent cadence in minutes. Omit for no schedule of its own.'),
    created_source: zod
        .enum(['user', 'ai_generated'])
        .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
        .optional()
        .describe(
            "Whether a human ('user') or an agent ('ai_generated') authored this check.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
        ),
    ai_model: zod
        .string()
        .max(dataQualityChecksPartialUpdateBodyAiModelMax)
        .optional()
        .describe('Model that generated the check, if AI-authored.'),
    confidence: zod
        .number()
        .min(dataQualityChecksPartialUpdateBodyConfidenceMin)
        .max(dataQualityChecksPartialUpdateBodyConfidenceMax)
        .nullish()
        .describe("AI author's confidence in the check, 0-1."),
    reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
})

/**
 * CRUD for data quality checks, plus the actions that run them and report on them.
 */
export const DataQualityChecksDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality check.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Run this check now. Returns the suite run to poll for the report.
 */
export const DataQualityChecksRunCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality check.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Recent run history for this check, newest first.
 */
export const DataQualityChecksRunsListParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data quality check.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * The check types this project can author, with the JSON schema of each type's config.
 */
export const DataQualityChecksCheckTypesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Health rollup for one table or view, from the denormalized status of its checks.
 */
export const DataQualityChecksHealthRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DataQualityChecksHealthRetrieveQueryParams = /* @__PURE__ */ zod.object({
    subject_type: zod.enum(['table', 'view']).describe("'table' or 'view'.\n\n\* `table` - table\n\* `view` - view"),
    subject_uuid: zod.string().describe('Id of the table or view to roll up.'),
})

/**
 * Run every enabled check on a table or view. Returns the suite run to poll for the report.
 */
export const DataQualityChecksRunForSubjectCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DataQualityChecksRunForSubjectCreateBody = /* @__PURE__ */ zod.object({
    subject_type: zod
        .enum(['table', 'view'])
        .describe('\* `table` - table\n\* `view` - view')
        .describe("'table' or 'view'.\n\n\* `table` - table\n\* `view` - view"),
    subject_uuid: zod.string().describe('Id of the table or view whose checks should run.'),
})
