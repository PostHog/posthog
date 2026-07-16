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

export const pulseBriefConfigsCreateBodySettingsOneMinAbsChangePctMax = 1000

export const pulseBriefConfigsCreateBodySettingsOneMinBaselineValueMin = 0
export const pulseBriefConfigsCreateBodySettingsOneMinBaselineValueMax = 1000000

export const pulseBriefConfigsCreateBodySettingsOneMaxAnchorInsightsMax = 100

export const pulseBriefConfigsCreateBodySettingsOneFallbackDashboardCountMax = 20

export const pulseBriefConfigsCreateBodySettingsOneConfidenceThresholdMin = 0
export const pulseBriefConfigsCreateBodySettingsOneConfidenceThresholdMax = 1

export const pulseBriefConfigsCreateBodySettingsOneMaxOpportunitiesMax = 20

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
    settings: zod
        .object({
            min_abs_change_pct: zod
                .number()
                .min(1)
                .max(pulseBriefConfigsCreateBodySettingsOneMinAbsChangePctMax)
                .optional()
                .describe('Minimum absolute percent change for a movement to count as significant. Default 20.'),
            min_baseline_value: zod
                .number()
                .min(pulseBriefConfigsCreateBodySettingsOneMinBaselineValueMin)
                .max(pulseBriefConfigsCreateBodySettingsOneMinBaselineValueMax)
                .optional()
                .describe('Minimum per-sample baseline volume before a movement is considered. Default 10.'),
            max_anchor_insights: zod
                .number()
                .min(1)
                .max(pulseBriefConfigsCreateBodySettingsOneMaxAnchorInsightsMax)
                .optional()
                .describe('Maximum anchor insights gathered per brief. Default 10.'),
            fallback_dashboard_count: zod
                .number()
                .min(1)
                .max(pulseBriefConfigsCreateBodySettingsOneFallbackDashboardCountMax)
                .optional()
                .describe('How many recent dashboards to pull insights from when no anchors are set. Default 3.'),
            confidence_threshold: zod
                .number()
                .min(pulseBriefConfigsCreateBodySettingsOneConfidenceThresholdMin)
                .max(pulseBriefConfigsCreateBodySettingsOneConfidenceThresholdMax)
                .optional()
                .describe('Minimum confidence for a section or opportunity to survive the gate. Default 0.6.'),
            max_opportunities: zod
                .number()
                .min(1)
                .max(pulseBriefConfigsCreateBodySettingsOneMaxOpportunitiesMax)
                .optional()
                .describe('Maximum opportunities kept per brief. Default 3.'),
        })
        .optional()
        .describe('Per-config tunables overriding the system defaults. Omitted knobs keep their default.'),
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

export const pulseBriefConfigsUpdateBodySettingsOneMinAbsChangePctMax = 1000

export const pulseBriefConfigsUpdateBodySettingsOneMinBaselineValueMin = 0
export const pulseBriefConfigsUpdateBodySettingsOneMinBaselineValueMax = 1000000

export const pulseBriefConfigsUpdateBodySettingsOneMaxAnchorInsightsMax = 100

export const pulseBriefConfigsUpdateBodySettingsOneFallbackDashboardCountMax = 20

export const pulseBriefConfigsUpdateBodySettingsOneConfidenceThresholdMin = 0
export const pulseBriefConfigsUpdateBodySettingsOneConfidenceThresholdMax = 1

export const pulseBriefConfigsUpdateBodySettingsOneMaxOpportunitiesMax = 20

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
    settings: zod
        .object({
            min_abs_change_pct: zod
                .number()
                .min(1)
                .max(pulseBriefConfigsUpdateBodySettingsOneMinAbsChangePctMax)
                .optional()
                .describe('Minimum absolute percent change for a movement to count as significant. Default 20.'),
            min_baseline_value: zod
                .number()
                .min(pulseBriefConfigsUpdateBodySettingsOneMinBaselineValueMin)
                .max(pulseBriefConfigsUpdateBodySettingsOneMinBaselineValueMax)
                .optional()
                .describe('Minimum per-sample baseline volume before a movement is considered. Default 10.'),
            max_anchor_insights: zod
                .number()
                .min(1)
                .max(pulseBriefConfigsUpdateBodySettingsOneMaxAnchorInsightsMax)
                .optional()
                .describe('Maximum anchor insights gathered per brief. Default 10.'),
            fallback_dashboard_count: zod
                .number()
                .min(1)
                .max(pulseBriefConfigsUpdateBodySettingsOneFallbackDashboardCountMax)
                .optional()
                .describe('How many recent dashboards to pull insights from when no anchors are set. Default 3.'),
            confidence_threshold: zod
                .number()
                .min(pulseBriefConfigsUpdateBodySettingsOneConfidenceThresholdMin)
                .max(pulseBriefConfigsUpdateBodySettingsOneConfidenceThresholdMax)
                .optional()
                .describe('Minimum confidence for a section or opportunity to survive the gate. Default 0.6.'),
            max_opportunities: zod
                .number()
                .min(1)
                .max(pulseBriefConfigsUpdateBodySettingsOneMaxOpportunitiesMax)
                .optional()
                .describe('Maximum opportunities kept per brief. Default 3.'),
        })
        .optional()
        .describe('Per-config tunables overriding the system defaults. Omitted knobs keep their default.'),
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

export const pulseBriefConfigsPartialUpdateBodySettingsOneMinAbsChangePctMax = 1000

export const pulseBriefConfigsPartialUpdateBodySettingsOneMinBaselineValueMin = 0
export const pulseBriefConfigsPartialUpdateBodySettingsOneMinBaselineValueMax = 1000000

export const pulseBriefConfigsPartialUpdateBodySettingsOneMaxAnchorInsightsMax = 100

export const pulseBriefConfigsPartialUpdateBodySettingsOneFallbackDashboardCountMax = 20

export const pulseBriefConfigsPartialUpdateBodySettingsOneConfidenceThresholdMin = 0
export const pulseBriefConfigsPartialUpdateBodySettingsOneConfidenceThresholdMax = 1

export const pulseBriefConfigsPartialUpdateBodySettingsOneMaxOpportunitiesMax = 20

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
    settings: zod
        .object({
            min_abs_change_pct: zod
                .number()
                .min(1)
                .max(pulseBriefConfigsPartialUpdateBodySettingsOneMinAbsChangePctMax)
                .optional()
                .describe('Minimum absolute percent change for a movement to count as significant. Default 20.'),
            min_baseline_value: zod
                .number()
                .min(pulseBriefConfigsPartialUpdateBodySettingsOneMinBaselineValueMin)
                .max(pulseBriefConfigsPartialUpdateBodySettingsOneMinBaselineValueMax)
                .optional()
                .describe('Minimum per-sample baseline volume before a movement is considered. Default 10.'),
            max_anchor_insights: zod
                .number()
                .min(1)
                .max(pulseBriefConfigsPartialUpdateBodySettingsOneMaxAnchorInsightsMax)
                .optional()
                .describe('Maximum anchor insights gathered per brief. Default 10.'),
            fallback_dashboard_count: zod
                .number()
                .min(1)
                .max(pulseBriefConfigsPartialUpdateBodySettingsOneFallbackDashboardCountMax)
                .optional()
                .describe('How many recent dashboards to pull insights from when no anchors are set. Default 3.'),
            confidence_threshold: zod
                .number()
                .min(pulseBriefConfigsPartialUpdateBodySettingsOneConfidenceThresholdMin)
                .max(pulseBriefConfigsPartialUpdateBodySettingsOneConfidenceThresholdMax)
                .optional()
                .describe('Minimum confidence for a section or opportunity to survive the gate. Default 0.6.'),
            max_opportunities: zod
                .number()
                .min(1)
                .max(pulseBriefConfigsPartialUpdateBodySettingsOneMaxOpportunitiesMax)
                .optional()
                .describe('Maximum opportunities kept per brief. Default 3.'),
        })
        .optional()
        .describe('Per-config tunables overriding the system defaults. Omitted knobs keep their default.'),
    enabled: zod.boolean().optional().describe('Whether this config generates briefs.'),
    deleted: zod
        .boolean()
        .optional()
        .describe(
            'Soft-delete flag. Deleted configs are hidden from lists but recoverable by patching this back to false.'
        ),
})

export const pulseBriefsGenerateCreateBodyPeriodOneDaysMax = 90

export const PulseBriefsGenerateCreateBody = /* @__PURE__ */ zod.object({
    config_id: zod
        .uuid()
        .nullish()
        .describe('Optional brief config to generate for. Omit for the zero-config default brief.'),
    period: zod
        .object({
            period_type: zod
                .enum(['last_n_days', 'since_last_run'])
                .describe('\* `last_n_days` - last_n_days\n\* `since_last_run` - since_last_run')
                .describe(
                    'How the brief window is chosen: a fixed lookback (last_n_days) or since the last ready brief.\n\n\* `last_n_days` - last_n_days\n\* `since_last_run` - since_last_run'
                ),
            days: zod
                .number()
                .min(1)
                .max(pulseBriefsGenerateCreateBodyPeriodOneDaysMax)
                .optional()
                .describe('Lookback length in days. Required and used only when period_type is last_n_days.'),
        })
        .optional()
        .describe('Period the brief should cover. Defaults to the last 7 days.'),
})
