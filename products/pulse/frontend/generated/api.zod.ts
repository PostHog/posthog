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

export const PulseBriefConfigsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(pulseBriefConfigsCreateBodyNameMax).describe('Human-readable name for this brief focus.'),
    focus_prompt: zod
        .string()
        .optional()
        .describe('Free-text focus steering gathering and tone, e.g. \"we\'re the feature flags team\".'),
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
    enabled: zod.boolean().optional().describe('Whether this config generates briefs.'),
})

export const pulseBriefConfigsUpdateBodyNameMax = 400

export const PulseBriefConfigsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(pulseBriefConfigsUpdateBodyNameMax).describe('Human-readable name for this brief focus.'),
    focus_prompt: zod
        .string()
        .optional()
        .describe('Free-text focus steering gathering and tone, e.g. \"we\'re the feature flags team\".'),
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
    enabled: zod.boolean().optional().describe('Whether this config generates briefs.'),
})

export const pulseBriefConfigsPartialUpdateBodyNameMax = 400

export const PulseBriefConfigsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(pulseBriefConfigsPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable name for this brief focus.'),
    focus_prompt: zod
        .string()
        .optional()
        .describe('Free-text focus steering gathering and tone, e.g. \"we\'re the feature flags team\".'),
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
    enabled: zod.boolean().optional().describe('Whether this config generates briefs.'),
})

export const pulseBriefsGenerateCreateBodyPeriodDaysDefault = 7
export const pulseBriefsGenerateCreateBodyPeriodDaysMax = 90

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
})
