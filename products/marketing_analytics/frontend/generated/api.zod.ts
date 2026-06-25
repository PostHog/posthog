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
 * Validate and persist the full set of per-channel lift-test calibrations (replaces the existing set). The only write endpoint in the MMM POC. Staff only.
 * @summary Replace MMM channel calibrations
 */
export const marketingAnalyticsMmmCalibrationsCreateBodyCalibrationsItemSourceDefault = `manual`

export const MarketingAnalyticsMmmCalibrationsCreateBody = /* @__PURE__ */ zod.object({
    calibrations: zod
        .array(
            zod.object({
                channel: zod.string().describe('Ad channel the calibration applies to (must match a spend channel).'),
                lift_pct: zod
                    .number()
                    .describe('Measured incremental lift as a percentage (e.g. 12.5 for a +12.5% lift).'),
                ci_low: zod.number().describe('Lower bound of the lift confidence interval, same units as lift_pct.'),
                ci_high: zod.number().describe('Upper bound of the lift confidence interval, same units as lift_pct.'),
                source: zod
                    .string()
                    .default(marketingAnalyticsMmmCalibrationsCreateBodyCalibrationsItemSourceDefault)
                    .describe("Origin of the calibration: 'manual' or 'experiment'."),
                experiment_id: zod
                    .string()
                    .nullish()
                    .describe('Source experiment ID when the calibration came from a PostHog experiment, else null.'),
            })
        )
        .describe('Full set of per-channel calibrations to persist (replaces the existing set).'),
})
