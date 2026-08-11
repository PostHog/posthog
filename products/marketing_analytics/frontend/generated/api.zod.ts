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
