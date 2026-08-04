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
 * Drop the preaggregated marketing cost data for a date range so it is recomputed from the warehouse tables, and optionally queue that rebuild in the background. Use this when the cost figures for a range are wrong or missing — for example after a warehouse sync was paused and backfilled, which can leave a window cached as zero.
 *
 * Idempotent and safe to retry. Read `effective_range` and `notes` on the response: the invalidated range can be wider than the one you asked for.
 * @summary Invalidate cost precompute for a date range
 */
export const marketingAnalyticsCostPrecomputeInvalidateCreateBodyRebuildDefault = true
export const marketingAnalyticsCostPrecomputeInvalidateCreateBodyDryRunDefault = false

export const MarketingAnalyticsCostPrecomputeInvalidateCreateBody = /* @__PURE__ */ zod.object({
    date_from: zod.iso.date().describe('First day to invalidate, inclusive (UTC).'),
    date_to: zod.iso.date().describe('Last day to invalidate, inclusive (UTC).'),
    rebuild: zod
        .boolean()
        .default(marketingAnalyticsCostPrecomputeInvalidateCreateBodyRebuildDefault)
        .describe(
            'Schedule a background rebuild of the range. Leave on unless you want the next read to pay for materialization itself.'
        ),
    dry_run: zod
        .boolean()
        .default(marketingAnalyticsCostPrecomputeInvalidateCreateBodyDryRunDefault)
        .describe('Report what would be invalidated without deleting anything.'),
})
