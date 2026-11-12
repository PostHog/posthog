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
 * Dismisses a recommendation or marks it as applied. Resolving it again replaces the earlier resolution. Returns 400 when the identity's rule never produces that combination of ids.
 * @summary Resolve a recommendation
 */
export const marketingAnalyticsRecommendationResolutionsCreateBodyIdentityOneCustomerIdMax = 64

export const marketingAnalyticsRecommendationResolutionsCreateBodyIdentityOneCampaignIdMax = 64

export const marketingAnalyticsRecommendationResolutionsCreateBodyIdentityOneSubjectMax = 10000

export const marketingAnalyticsRecommendationResolutionsCreateBodyNameDefault = ``
export const marketingAnalyticsRecommendationResolutionsCreateBodyNameMax = 400

export const MarketingAnalyticsRecommendationResolutionsCreateBody = /* @__PURE__ */ zod.object({
    identity: zod
        .object({
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
                    'keyword_tracking',
                ])
                .describe(
                    '\* `budget_constrained` - Budget Constrained\n\* `brand_leak` - Brand Leak\n\* `scale_campaign` - Scale Campaign\n\* `review_campaign` - Review Campaign\n\* `policy_limited` - Policy Limited\n\* `brand_overlap` - Brand Overlap\n\* `content_gap` - Content Gap\n\* `keyword_gap` - Keyword Gap\n\* `spend_without_conversions` - Spend Without Conversions\n\* `striking_distance` - Striking Distance\n\* `keyword_tracking` - Keyword Tracking'
                )
                .describe(
                    'The rule that produced the recommendation.\n\n\* `budget_constrained` - Budget Constrained\n\* `brand_leak` - Brand Leak\n\* `scale_campaign` - Scale Campaign\n\* `review_campaign` - Review Campaign\n\* `policy_limited` - Policy Limited\n\* `brand_overlap` - Brand Overlap\n\* `content_gap` - Content Gap\n\* `keyword_gap` - Keyword Gap\n\* `spend_without_conversions` - Spend Without Conversions\n\* `striking_distance` - Striking Distance\n\* `keyword_tracking` - Keyword Tracking'
                ),
            source_type: zod
                .enum(['google_ads'])
                .describe('\* `google_ads` - Google Ads')
                .describe('The ad platform the ids belong to.\n\n\* `google_ads` - Google Ads'),
            customer_id: zod
                .string()
                .max(marketingAnalyticsRecommendationResolutionsCreateBodyIdentityOneCustomerIdMax)
                .describe('The Google Ads account id. Empty when the recommendation is not tied to one account.'),
            campaign_id: zod
                .string()
                .max(marketingAnalyticsRecommendationResolutionsCreateBodyIdentityOneCampaignIdMax)
                .describe('The Google Ads campaign id. Empty when the recommendation is not about one campaign.'),
            subject: zod
                .string()
                .max(marketingAnalyticsRecommendationResolutionsCreateBodyIdentityOneSubjectMax)
                .describe(
                    'The search term, or the budget id for a budget recommendation. Empty when the campaign id names the subject.'
                ),
        })
        .describe("The recommendation's `identity` from the recommendations query, sent as is."),
    name: zod
        .string()
        .max(marketingAnalyticsRecommendationResolutionsCreateBodyNameMax)
        .default(marketingAnalyticsRecommendationResolutionsCreateBodyNameDefault)
        .describe(
            'A display label for the recommendation, such as the campaign name or the search term. The activity log shows it. It is not part of the identity.'
        ),
    resolution: zod
        .enum(['dismissed', 'applied'])
        .describe('\* `dismissed` - Dismissed\n\* `applied` - Applied')
        .describe(
            'Dismissed hides the recommendation. Applied marks that someone made the change it suggests.\n\n\* `dismissed` - Dismissed\n\* `applied` - Applied'
        ),
})
