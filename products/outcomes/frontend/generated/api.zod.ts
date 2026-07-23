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
 * Create, read, update, and delete outcome definitions, and inspect who reached them.
 */
export const outcomesCreateBodyNameMax = 400

export const outcomesCreateBodyTargetEventMax = 400

export const outcomesCreateBodyThresholdMax = 2147483647

export const OutcomesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(outcomesCreateBodyNameMax).describe('Human-readable name of the outcome.'),
    description: zod.string().optional().describe('What reaching this outcome means for the business.'),
    target_event: zod
        .string()
        .max(outcomesCreateBodyTargetEventMax)
        .describe('Name of the event the person must perform to reach the outcome.'),
    threshold: zod
        .number()
        .min(1)
        .max(outcomesCreateBodyThresholdMax)
        .optional()
        .describe('Minimum number of times the person must perform the target event.'),
})

/**
 * Create, read, update, and delete outcome definitions, and inspect who reached them.
 */
export const outcomesUpdateBodyNameMax = 400

export const outcomesUpdateBodyTargetEventMax = 400

export const outcomesUpdateBodyThresholdMax = 2147483647

export const OutcomesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(outcomesUpdateBodyNameMax).describe('Human-readable name of the outcome.'),
    description: zod.string().optional().describe('What reaching this outcome means for the business.'),
    target_event: zod
        .string()
        .max(outcomesUpdateBodyTargetEventMax)
        .describe('Name of the event the person must perform to reach the outcome.'),
    threshold: zod
        .number()
        .min(1)
        .max(outcomesUpdateBodyThresholdMax)
        .optional()
        .describe('Minimum number of times the person must perform the target event.'),
})

/**
 * Create, read, update, and delete outcome definitions, and inspect who reached them.
 */
export const outcomesPartialUpdateBodyNameMax = 400

export const outcomesPartialUpdateBodyTargetEventMax = 400

export const outcomesPartialUpdateBodyThresholdMax = 2147483647

export const OutcomesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(outcomesPartialUpdateBodyNameMax).optional().describe('Human-readable name of the outcome.'),
    description: zod.string().optional().describe('What reaching this outcome means for the business.'),
    target_event: zod
        .string()
        .max(outcomesPartialUpdateBodyTargetEventMax)
        .optional()
        .describe('Name of the event the person must perform to reach the outcome.'),
    threshold: zod
        .number()
        .min(1)
        .max(outcomesPartialUpdateBodyThresholdMax)
        .optional()
        .describe('Minimum number of times the person must perform the target event.'),
})
