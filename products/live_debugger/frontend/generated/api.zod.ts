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
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsCreateBodyLineNumberMin = 0
export const liveDebuggerBreakpointsCreateBodyLineNumberMax = 2147483647

export const LiveDebuggerBreakpointsCreateBody = /* @__PURE__ */ zod.object({
    repository: zod.string().nullish(),
    filename: zod.string(),
    line_number: zod
        .number()
        .min(liveDebuggerBreakpointsCreateBodyLineNumberMin)
        .max(liveDebuggerBreakpointsCreateBodyLineNumberMax),
    enabled: zod.boolean().optional(),
    condition: zod.string().nullish(),
})

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsUpdateBodyLineNumberMin = 0
export const liveDebuggerBreakpointsUpdateBodyLineNumberMax = 2147483647

export const LiveDebuggerBreakpointsUpdateBody = /* @__PURE__ */ zod.object({
    repository: zod.string().nullish(),
    filename: zod.string(),
    line_number: zod
        .number()
        .min(liveDebuggerBreakpointsUpdateBodyLineNumberMin)
        .max(liveDebuggerBreakpointsUpdateBodyLineNumberMax),
    enabled: zod.boolean().optional(),
    condition: zod.string().nullish(),
})

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsPartialUpdateBodyLineNumberMin = 0
export const liveDebuggerBreakpointsPartialUpdateBodyLineNumberMax = 2147483647

export const LiveDebuggerBreakpointsPartialUpdateBody = /* @__PURE__ */ zod.object({
    repository: zod.string().nullish(),
    filename: zod.string().optional(),
    line_number: zod
        .number()
        .min(liveDebuggerBreakpointsPartialUpdateBodyLineNumberMin)
        .max(liveDebuggerBreakpointsPartialUpdateBodyLineNumberMax)
        .optional(),
    enabled: zod.boolean().optional(),
    condition: zod.string().nullish(),
})
