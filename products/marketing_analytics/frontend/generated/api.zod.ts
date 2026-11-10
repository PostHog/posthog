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
 * Apply one or more setup operations from the setup plan, atomically. Either every operation lands or none does — a partially-applied batch has no well-defined undo. Returns `undo_ops`, computed from the pre-change state, which can be POSTed back to reverse the batch. Only send `apply` payloads returned by setup_plan.
 * @summary Apply setup operations
 */
export const marketingAnalyticsApplySetupOpsCreateBodySourceDefault = `setup_tab`

export const MarketingAnalyticsApplySetupOpsCreateBody = /* @__PURE__ */ zod.object({
    ops: zod
        .array(zod.unknown())
        .describe(
            'Operations to apply, in order. Send `apply` payloads returned verbatim by setup_plan — never hand-craft one. Navigate-only ops (open_oauth, open_source_wizard, open_settings, fix_platform_urls) are rejected: they describe something a browser or a human does.'
        ),
    source: zod
        .enum(['setup_tab', 'apply_all_safe', 'mcp'])
        .describe('\* `setup_tab` - setup_tab\n\* `apply_all_safe` - apply_all_safe\n\* `mcp` - mcp')
        .default(marketingAnalyticsApplySetupOpsCreateBodySourceDefault)
        .describe(
            'Where the request came from, recorded in the activity log\n\n\* `setup_tab` - setup_tab\n\* `apply_all_safe` - apply_all_safe\n\* `mcp` - mcp'
        ),
})

/**
 * Change one conversion goal in place. Fields you send are merged into the stored goal, the rest are kept, and the goal keeps its position in the list. Sending a different `kind` replaces the goal instead, since the shapes don't share their fields.
 * @summary Update conversion goal
 */
export const MarketingAnalyticsConversionGoalsUpdatePartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Add one conversion goal to the project. The server assigns conversion_goal_id and appends the goal to the end of the list, leaving existing goals untouched.
 * @summary Create conversion goal
 */
export const MarketingAnalyticsConversionGoalsCreateCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * @summary Start a conversion recommendation analysis
 */
export const marketingAnalyticsConversionRecommendationsStartCreateBodyRefreshDefault = false

export const MarketingAnalyticsConversionRecommendationsStartCreateBody = /* @__PURE__ */ zod.object({
    refresh: zod
        .boolean()
        .default(marketingAnalyticsConversionRecommendationsStartCreateBodyRefreshDefault)
        .describe(
            'False starts the first 30-day analysis once. True requests a new 14-day analysis; use only after an explicit user request.'
        ),
})

export const MarketingAnalyticsConversionRecordingsListBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Marketing analytics recommendations that someone in the project dismissed or marked as applied. The
 * recommendations query leaves a resolved recommendation out for everyone in the project until someone deletes
 * its resolution.
 */
export const marketingAnalyticsRecommendationResolutionsCreateBodySourceTypeDefault = `google_ads`
export const marketingAnalyticsRecommendationResolutionsCreateBodyCustomerIdDefault = ``
export const marketingAnalyticsRecommendationResolutionsCreateBodyCustomerIdMax = 64

export const marketingAnalyticsRecommendationResolutionsCreateBodyCampaignIdDefault = ``
export const marketingAnalyticsRecommendationResolutionsCreateBodyCampaignIdMax = 64

export const marketingAnalyticsRecommendationResolutionsCreateBodySubjectDefault = ``
export const marketingAnalyticsRecommendationResolutionsCreateBodySubjectMax = 1024

export const marketingAnalyticsRecommendationResolutionsCreateBodySnapshotOneActionMax = 1000

export const marketingAnalyticsRecommendationResolutionsCreateBodySnapshotOneCurrencyMax = 8

export const MarketingAnalyticsRecommendationResolutionsCreateBody = /* @__PURE__ */ zod.object({
    rule: zod
        .enum([
            'budget_constrained',
            'brand_leak',
            'scale_campaign',
            'review_campaign',
            'policy_limited',
            'brand_overlap',
            'content_gap',
            'keyword_gap',
            'spend_without_conversions',
            'striking_distance',
        ])
        .describe(
            '\* `budget_constrained` - Budget Constrained\n\* `brand_leak` - Brand Leak\n\* `scale_campaign` - Scale Campaign\n\* `review_campaign` - Review Campaign\n\* `policy_limited` - Policy Limited\n\* `brand_overlap` - Brand Overlap\n\* `content_gap` - Content Gap\n\* `keyword_gap` - Keyword Gap\n\* `spend_without_conversions` - Spend Without Conversions\n\* `striking_distance` - Striking Distance'
        )
        .describe(
            'The rule that produced the resolved recommendation.\n\n\* `budget_constrained` - Budget Constrained\n\* `brand_leak` - Brand Leak\n\* `scale_campaign` - Scale Campaign\n\* `review_campaign` - Review Campaign\n\* `policy_limited` - Policy Limited\n\* `brand_overlap` - Brand Overlap\n\* `content_gap` - Content Gap\n\* `keyword_gap` - Keyword Gap\n\* `spend_without_conversions` - Spend Without Conversions\n\* `striking_distance` - Striking Distance'
        ),
    source_type: zod
        .enum(['google_ads'])
        .describe('\* `google_ads` - Google Ads')
        .default(marketingAnalyticsRecommendationResolutionsCreateBodySourceTypeDefault)
        .describe("The recommendation's `identity.source_type`.\n\n\* `google_ads` - Google Ads"),
    customer_id: zod
        .string()
        .max(marketingAnalyticsRecommendationResolutionsCreateBodyCustomerIdMax)
        .default(marketingAnalyticsRecommendationResolutionsCreateBodyCustomerIdDefault)
        .describe("The recommendation's `identity.customer_id`."),
    campaign_id: zod
        .string()
        .max(marketingAnalyticsRecommendationResolutionsCreateBodyCampaignIdMax)
        .default(marketingAnalyticsRecommendationResolutionsCreateBodyCampaignIdDefault)
        .describe("The recommendation's `identity.campaign_id`."),
    subject: zod
        .string()
        .max(marketingAnalyticsRecommendationResolutionsCreateBodySubjectMax)
        .default(marketingAnalyticsRecommendationResolutionsCreateBodySubjectDefault)
        .describe("The recommendation's `identity.subject`."),
    resolution: zod
        .enum(['dismissed', 'applied'])
        .describe('\* `dismissed` - Dismissed\n\* `applied` - Applied')
        .describe(
            'Dismissed hides the recommendation. Applied marks that someone made the change it suggests.\n\n\* `dismissed` - Dismissed\n\* `applied` - Applied'
        ),
    snapshot: zod
        .union([
            zod.object({
                action: zod
                    .string()
                    .max(marketingAnalyticsRecommendationResolutionsCreateBodySnapshotOneActionMax)
                    .describe("The recommendation's `action` when it was resolved."),
                impact: zod.number().nullish().describe("The recommendation's `impact` when it was resolved."),
                currency: zod
                    .string()
                    .max(marketingAnalyticsRecommendationResolutionsCreateBodySnapshotOneCurrencyMax)
                    .nullish()
                    .describe("The recommendation's `currency` when it was resolved."),
            }),
            zod.null(),
        ])
        .optional()
        .describe('What the recommendation suggested when it was resolved.'),
})
