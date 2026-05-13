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
 * Install a hogtrace program. The program will be picked up by the client-side runtime and its probes will start emitting events on hit. Returns the full program record including its newly assigned id.
 * @summary Install a live debugger program
 */
export const LiveDebuggerProgramsCreateBody = /* @__PURE__ */ zod
    .object({
        code: zod
            .string()
            .describe(
                'The hogtrace program source code to install. This is executed by the client-side runtime to instrument production code with probes.'
            ),
        description: zod
            .string()
            .optional()
            .describe('Human-readable description of what this program does and why it was installed.'),
    })
    .describe('Full representation of a live debugger program, including its code.')
