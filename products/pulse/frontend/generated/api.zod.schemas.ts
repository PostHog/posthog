/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const BriefAnchorsApi = zod.object({
    dashboards: zod.array(zod.number()).optional().describe('IDs of the dashboards this brief is anchored on.'),
    insights: zod.array(zod.string()).optional().describe('Short IDs of the insights this brief is anchored on.'),
})

export type BriefAnchorsApi = zod.input<typeof BriefAnchorsApi>
export type BriefAnchorsApiOutput = zod.output<typeof BriefAnchorsApi>

export const briefSettingsApiMinAbsChangePctMax = 1000

export const briefSettingsApiMinBaselineValueMin = 0
export const briefSettingsApiMinBaselineValueMax = 1000000

export const briefSettingsApiMaxAnchorInsightsMax = 100

export const briefSettingsApiFallbackDashboardCountMax = 20

export const briefSettingsApiConfidenceThresholdMin = 0
export const briefSettingsApiConfidenceThresholdMax = 1

export const briefSettingsApiMaxOpportunitiesMax = 20

export const briefSettingsApiMaxAnnotationsMax = 100

export const BriefSettingsApi = zod.object({
    min_abs_change_pct: zod
        .number()
        .min(1)
        .max(briefSettingsApiMinAbsChangePctMax)
        .optional()
        .describe('Minimum absolute percent change for a movement to count as significant. Default 20.'),
    min_baseline_value: zod
        .number()
        .min(briefSettingsApiMinBaselineValueMin)
        .max(briefSettingsApiMinBaselineValueMax)
        .optional()
        .describe('Minimum per-sample baseline volume before a movement is considered. Default 10.'),
    max_anchor_insights: zod
        .number()
        .min(1)
        .max(briefSettingsApiMaxAnchorInsightsMax)
        .optional()
        .describe('Maximum anchor insights gathered per brief. Default 10.'),
    fallback_dashboard_count: zod
        .number()
        .min(1)
        .max(briefSettingsApiFallbackDashboardCountMax)
        .optional()
        .describe('How many recent dashboards to pull insights from when no anchors are set. Default 3.'),
    confidence_threshold: zod
        .number()
        .min(briefSettingsApiConfidenceThresholdMin)
        .max(briefSettingsApiConfidenceThresholdMax)
        .optional()
        .describe('Minimum confidence for a section or opportunity to survive the gate. Default 0.6.'),
    max_opportunities: zod
        .number()
        .min(1)
        .max(briefSettingsApiMaxOpportunitiesMax)
        .optional()
        .describe('Maximum opportunities kept per brief. Default 3.'),
    max_annotations: zod
        .number()
        .min(1)
        .max(briefSettingsApiMaxAnnotationsMax)
        .optional()
        .describe('Maximum annotations gathered as context per brief. Default 20.'),
})

export type BriefSettingsApi = zod.input<typeof BriefSettingsApi>
export type BriefSettingsApiOutput = zod.output<typeof BriefSettingsApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const briefConfigApiNameMax = 400

export const briefConfigApiFocusPromptMax = 2000

export const BriefConfigApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(briefConfigApiNameMax).describe('Human-readable name for this brief focus.'),
    focus_prompt: zod
        .string()
        .max(briefConfigApiFocusPromptMax)
        .optional()
        .describe(
            'Free-text focus steering gathering and tone, e.g. \"we\'re the feature flags team\". Max 2000 characters.'
        ),
    anchors: BriefAnchorsApi.optional().describe(
        "Anchor resources the brief gathers movements from. Empty anchors fall back to the team's most recently accessed dashboards."
    ),
    settings: BriefSettingsApi.optional().describe(
        'Per-config tunables overriding the system defaults. Omitted knobs keep their default.'
    ),
    enabled: zod.boolean().optional().describe('Whether this config generates briefs.'),
    deleted: zod
        .boolean()
        .optional()
        .describe(
            'Soft-delete flag. Deleted configs are hidden from lists but recoverable by patching this back to false.'
        ),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: zod.union([UserBasicApi, zod.null()]).describe('User who created the config.'),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type BriefConfigApi = zod.input<typeof BriefConfigApi>
export type BriefConfigApiOutput = zod.output<typeof BriefConfigApi>

export const PaginatedBriefConfigListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(BriefConfigApi),
})

export type PaginatedBriefConfigListApi = zod.input<typeof PaginatedBriefConfigListApi>
export type PaginatedBriefConfigListApiOutput = zod.output<typeof PaginatedBriefConfigListApi>

export const patchedBriefConfigApiNameMax = 400

export const patchedBriefConfigApiFocusPromptMax = 2000

export const PatchedBriefConfigApi = zod.object({
    id: zod.uuid().optional(),
    name: zod
        .string()
        .max(patchedBriefConfigApiNameMax)
        .optional()
        .describe('Human-readable name for this brief focus.'),
    focus_prompt: zod
        .string()
        .max(patchedBriefConfigApiFocusPromptMax)
        .optional()
        .describe(
            'Free-text focus steering gathering and tone, e.g. \"we\'re the feature flags team\". Max 2000 characters.'
        ),
    anchors: BriefAnchorsApi.optional().describe(
        "Anchor resources the brief gathers movements from. Empty anchors fall back to the team's most recently accessed dashboards."
    ),
    settings: BriefSettingsApi.optional().describe(
        'Per-config tunables overriding the system defaults. Omitted knobs keep their default.'
    ),
    enabled: zod.boolean().optional().describe('Whether this config generates briefs.'),
    deleted: zod
        .boolean()
        .optional()
        .describe(
            'Soft-delete flag. Deleted configs are hidden from lists but recoverable by patching this back to false.'
        ),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: zod.union([UserBasicApi, zod.null()]).optional().describe('User who created the config.'),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedBriefConfigApi = zod.input<typeof PatchedBriefConfigApi>
export type PatchedBriefConfigApiOutput = zod.output<typeof PatchedBriefConfigApi>

export const ProductBriefStatusEnumApi = zod
    .enum(['generating', 'ready', 'quiet', 'failed'])
    .describe('\* `generating` - Generating\n\* `ready` - Ready\n\* `quiet` - Quiet\n\* `failed` - Failed')

export type ProductBriefStatusEnumApi = zod.input<typeof ProductBriefStatusEnumApi>
export type ProductBriefStatusEnumApiOutput = zod.output<typeof ProductBriefStatusEnumApi>

export const ProductBriefTriggerEnumApi = zod
    .enum(['on_demand', 'scheduled'])
    .describe('\* `on_demand` - On Demand\n\* `scheduled` - Scheduled')

export type ProductBriefTriggerEnumApi = zod.input<typeof ProductBriefTriggerEnumApi>
export type ProductBriefTriggerEnumApiOutput = zod.output<typeof ProductBriefTriggerEnumApi>

export const PeriodTypeEnumApi = zod
    .enum(['last_n_days', 'since_last_run'])
    .describe('\* `last_n_days` - last_n_days\n\* `since_last_run` - since_last_run')

export type PeriodTypeEnumApi = zod.input<typeof PeriodTypeEnumApi>
export type PeriodTypeEnumApiOutput = zod.output<typeof PeriodTypeEnumApi>

export const periodApiDaysMax = 90

export const PeriodApi = zod.object({
    period_type: PeriodTypeEnumApi.describe(
        'How the brief window is chosen: a fixed lookback (last_n_days) or since the last ready brief.\n\n\* `last_n_days` - last_n_days\n\* `since_last_run` - since_last_run'
    ),
    days: zod
        .number()
        .min(1)
        .max(periodApiDaysMax)
        .optional()
        .describe('Lookback length in days. Required and used only when period_type is last_n_days.'),
})

export type PeriodApi = zod.input<typeof PeriodApi>
export type PeriodApiOutput = zod.output<typeof PeriodApi>

export const ProductBriefListApi = zod.object({
    id: zod.uuid(),
    config: zod.uuid().nullable().describe('The brief config this brief was generated for, if any.'),
    status: ProductBriefStatusEnumApi.describe(
        'Lifecycle status: generating, ready, quiet (nothing confident to say), or failed.\n\n\* `generating` - Generating\n\* `ready` - Ready\n\* `quiet` - Quiet\n\* `failed` - Failed'
    ),
    trigger: ProductBriefTriggerEnumApi.describe(
        'What started the generation: on_demand or scheduled.\n\n\* `on_demand` - On Demand\n\* `scheduled` - Scheduled'
    ),
    period: PeriodApi.describe('The resolved-at-gather period spec the brief covers.'),
    sources_used: zod.array(zod.string()).describe('Names of the brief sources that contributed items.'),
    error: zod.string().nullable().describe('Error detail when status is failed.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: zod.union([UserBasicApi, zod.null()]).describe('User who requested the brief.'),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type ProductBriefListApi = zod.input<typeof ProductBriefListApi>
export type ProductBriefListApiOutput = zod.output<typeof ProductBriefListApi>

export const PaginatedProductBriefListListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ProductBriefListApi),
})

export type PaginatedProductBriefListListApi = zod.input<typeof PaginatedProductBriefListListApi>
export type PaginatedProductBriefListListApiOutput = zod.output<typeof PaginatedProductBriefListListApi>

export const BriefSectionCitationApi = zod.object({
    type: zod.string().describe('Cited resource type, e.g. insight or dashboard.'),
    ref: zod.string().describe('Stable id of the cited resource within its type.'),
    label: zod.string().describe('Human-readable name of the cited resource, for display.'),
    url: zod.string().describe('Deep link into the app, or empty when the resource has no navigable target.'),
})

export type BriefSectionCitationApi = zod.input<typeof BriefSectionCitationApi>
export type BriefSectionCitationApiOutput = zod.output<typeof BriefSectionCitationApi>

export const BriefSectionApi = zod.object({
    kind: zod.string().describe('Section kind, e.g. what_happened or what_to_build_next.'),
    title: zod.string().describe('Short section heading.'),
    markdown: zod.string().describe('Section body rendered as markdown.'),
    citations: zod.array(BriefSectionCitationApi).describe('PostHog resources this section cites as evidence.'),
    confidence: zod.number().describe('Model confidence in this section, 0.0-1.0.'),
})

export type BriefSectionApi = zod.input<typeof BriefSectionApi>
export type BriefSectionApiOutput = zod.output<typeof BriefSectionApi>

export const ProductBriefApi = zod.object({
    id: zod.uuid(),
    config: zod.uuid().nullable().describe('The brief config this brief was generated for, if any.'),
    status: ProductBriefStatusEnumApi.describe(
        'Lifecycle status: generating, ready, quiet (nothing confident to say), or failed.\n\n\* `generating` - Generating\n\* `ready` - Ready\n\* `quiet` - Quiet\n\* `failed` - Failed'
    ),
    trigger: ProductBriefTriggerEnumApi.describe(
        'What started the generation: on_demand or scheduled.\n\n\* `on_demand` - On Demand\n\* `scheduled` - Scheduled'
    ),
    period: PeriodApi.describe('The resolved-at-gather period spec the brief covers.'),
    sections: zod.array(BriefSectionApi).describe('Generated brief sections, most important first.'),
    sources_used: zod.array(zod.string()).describe('Names of the brief sources that contributed items.'),
    error: zod.string().nullable().describe('Error detail when status is failed.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: zod.union([UserBasicApi, zod.null()]).describe('User who requested the brief.'),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type ProductBriefApi = zod.input<typeof ProductBriefApi>
export type ProductBriefApiOutput = zod.output<typeof ProductBriefApi>

export const GenerateBriefRequestApi = zod.object({
    config_id: zod
        .uuid()
        .nullish()
        .describe('Optional brief config to generate for. Omit for the zero-config default brief.'),
    period: PeriodApi.optional().describe('Period the brief should cover. Defaults to the last 7 days.'),
})

export type GenerateBriefRequestApi = zod.input<typeof GenerateBriefRequestApi>
export type GenerateBriefRequestApiOutput = zod.output<typeof GenerateBriefRequestApi>
