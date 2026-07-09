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

export const pulseBriefConfigsCreateBodyNameMax = 400

export const pulseBriefConfigsCreateBodyFocusPromptMax = 2000

export const PulseBriefConfigsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(pulseBriefConfigsCreateBodyNameMax).describe('Human-readable name for this brief focus.'),
    focus_prompt: zod
        .string()
        .max(pulseBriefConfigsCreateBodyFocusPromptMax)
        .optional()
        .describe(
            'Free-text focus steering gathering and tone, e.g. \"we\'re the feature flags team\". Max 2000 characters.'
        ),
    anchors: zod
        .object({
            dashboards: zod.array(zod.number()).optional().describe('IDs of the dashboards this brief is anchored on.'),
            insights: zod
                .array(zod.string())
                .optional()
                .describe('Short IDs of the insights this brief is anchored on.'),
        })
        .optional()
        .describe(
            "Anchor resources the brief gathers movements from. Empty anchors fall back to the team's most recently accessed dashboards."
        ),
    goal: zod
        .string()
        .optional()
        .describe(
            'Free-text goal this focus drives toward, e.g. \"increase subscription usage\". Briefs open with progress toward it.'
        ),
    goal_metric: zod
        .union([
            zod.object({
                insight_short_id: zod
                    .string()
                    .describe('Short ID of the team-owned trends insight tracking progress toward the goal.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Insight whose trend measures progress toward the goal. Null when the goal is qualitative.'),
    enabled: zod.boolean().optional().describe('Whether this config generates briefs.'),
    deleted: zod
        .boolean()
        .optional()
        .describe(
            'Soft-delete flag. Deleted configs are hidden from lists but recoverable by patching this back to false.'
        ),
})

export const pulseBriefConfigsUpdateBodyNameMax = 400

export const pulseBriefConfigsUpdateBodyFocusPromptMax = 2000

export const PulseBriefConfigsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(pulseBriefConfigsUpdateBodyNameMax).describe('Human-readable name for this brief focus.'),
    focus_prompt: zod
        .string()
        .max(pulseBriefConfigsUpdateBodyFocusPromptMax)
        .optional()
        .describe(
            'Free-text focus steering gathering and tone, e.g. \"we\'re the feature flags team\". Max 2000 characters.'
        ),
    anchors: zod
        .object({
            dashboards: zod.array(zod.number()).optional().describe('IDs of the dashboards this brief is anchored on.'),
            insights: zod
                .array(zod.string())
                .optional()
                .describe('Short IDs of the insights this brief is anchored on.'),
        })
        .optional()
        .describe(
            "Anchor resources the brief gathers movements from. Empty anchors fall back to the team's most recently accessed dashboards."
        ),
    goal: zod
        .string()
        .optional()
        .describe(
            'Free-text goal this focus drives toward, e.g. \"increase subscription usage\". Briefs open with progress toward it.'
        ),
    goal_metric: zod
        .union([
            zod.object({
                insight_short_id: zod
                    .string()
                    .describe('Short ID of the team-owned trends insight tracking progress toward the goal.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Insight whose trend measures progress toward the goal. Null when the goal is qualitative.'),
    enabled: zod.boolean().optional().describe('Whether this config generates briefs.'),
    deleted: zod
        .boolean()
        .optional()
        .describe(
            'Soft-delete flag. Deleted configs are hidden from lists but recoverable by patching this back to false.'
        ),
})

export const pulseBriefConfigsPartialUpdateBodyNameMax = 400

export const pulseBriefConfigsPartialUpdateBodyFocusPromptMax = 2000

export const PulseBriefConfigsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(pulseBriefConfigsPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable name for this brief focus.'),
    focus_prompt: zod
        .string()
        .max(pulseBriefConfigsPartialUpdateBodyFocusPromptMax)
        .optional()
        .describe(
            'Free-text focus steering gathering and tone, e.g. \"we\'re the feature flags team\". Max 2000 characters.'
        ),
    anchors: zod
        .object({
            dashboards: zod.array(zod.number()).optional().describe('IDs of the dashboards this brief is anchored on.'),
            insights: zod
                .array(zod.string())
                .optional()
                .describe('Short IDs of the insights this brief is anchored on.'),
        })
        .optional()
        .describe(
            "Anchor resources the brief gathers movements from. Empty anchors fall back to the team's most recently accessed dashboards."
        ),
    goal: zod
        .string()
        .optional()
        .describe(
            'Free-text goal this focus drives toward, e.g. \"increase subscription usage\". Briefs open with progress toward it.'
        ),
    goal_metric: zod
        .union([
            zod.object({
                insight_short_id: zod
                    .string()
                    .describe('Short ID of the team-owned trends insight tracking progress toward the goal.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Insight whose trend measures progress toward the goal. Null when the goal is qualitative.'),
    enabled: zod.boolean().optional().describe('Whether this config generates briefs.'),
    deleted: zod
        .boolean()
        .optional()
        .describe(
            'Soft-delete flag. Deleted configs are hidden from lists but recoverable by patching this back to false.'
        ),
})

export const PulseBriefsFeedbackCreateBody = /* @__PURE__ */ zod.object({
    helpful: zod
        .boolean()
        .nullable()
        .describe('True marks the item helpful, false marks it not helpful, and null clears your vote.'),
})

export const pulseBriefsGenerateCreateBodyPeriodDaysDefault = 7
export const pulseBriefsGenerateCreateBodyPeriodDaysMax = 90

export const pulseBriefsGenerateCreateBodyMissionDefault = `general_brief`

export const PulseBriefsGenerateCreateBody = /* @__PURE__ */ zod.object({
    config_id: zod
        .uuid()
        .nullish()
        .describe('Optional brief config to generate for. Omit for the zero-config default brief.'),
    period_days: zod
        .number()
        .min(1)
        .max(pulseBriefsGenerateCreateBodyPeriodDaysMax)
        .default(pulseBriefsGenerateCreateBodyPeriodDaysDefault)
        .describe('Number of days the brief should cover. Defaults to 7.'),
    mission: zod
        .enum(['general_brief', 'query_performance'])
        .describe('\* `general_brief` - general_brief\n\* `query_performance` - query_performance')
        .default(pulseBriefsGenerateCreateBodyMissionDefault)
        .describe(
            'Mission the agent engine runs. Defaults to the general brief; query_performance is internal (staff only) and requires the agent engine.\n\n\* `general_brief` - general_brief\n\* `query_performance` - query_performance'
        ),
})

export const PulseOpportunitiesFeedbackCreateBody = /* @__PURE__ */ zod.object({
    helpful: zod
        .boolean()
        .nullable()
        .describe('True marks the item helpful, false marks it not helpful, and null clears your vote.'),
})

/**
 * Forwards SQL to the restricted autoresearch ClickHouse user for query-performance analysis (query_log_archive and related tables). Read-only; row and time limited.
 * @summary Run a read-only query against the autoresearch test cluster
 */
export const queryPerformanceProxyExecuteTestCreateBodySqlMax = 65536

export const QueryPerformanceProxyExecuteTestCreateBody = /* @__PURE__ */ zod.object({
    sql: zod
        .string()
        .max(queryPerformanceProxyExecuteTestCreateBodySqlMax)
        .describe('ClickHouse SQL to run against the test cluster.'),
})
