/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Retrieve the current signal autostart autonomy config for a user. Returns the user's personal `autostart_priority` override (P0–P4) if set, or null when the user inherits the team default. Returns 404 when the user has not opted in.
 * @summary Get a user's signal autostart config
 */
export const UsersSignalAutonomyRetrieveParams = /* @__PURE__ */ zod.object({
    user_id: zod
        .string()
        .describe(
            "PostHog user identifier. Pass `@me` to target the currently authenticated user. Staff users may pass another user's primary key."
        ),
})

/**
 * Opt the user in to signal autonomy, or update their `autostart_priority` threshold. `autostart_priority` accepts P0, P1, P2, P3, P4, or null (inherit team default). P0 starts autonomous work for the broadest set of reports, P4 only for the highest priority. Setting a priority means PostHog Code will start automatically on reports at or above that priority that are assigned to this user.
 * @summary Opt in or update signal autostart config
 */
export const UsersSignalAutonomyUpdateParams = /* @__PURE__ */ zod.object({
    user_id: zod
        .string()
        .describe(
            "PostHog user identifier. Pass `@me` to target the currently authenticated user. Staff users may pass another user's primary key."
        ),
})

export const UsersSignalAutonomyUpdateBody = /* @__PURE__ */ zod.object({
    autostart_priority: zod
        .union([
            zod
                .enum(['P0', 'P1', 'P2', 'P3', 'P4'])
                .describe('* `P0` - P0\n* `P1` - P1\n* `P2` - P2\n* `P3` - P3\n* `P4` - P4'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Minimum priority at which PostHog Code will autostart work on signal reports assigned to this user. One of P0, P1, P2, P3, P4. Set to null to inherit the team default. P0 is the broadest (autostart on any priority), P4 is the narrowest (only highest priority).\n\n* `P0` - P0\n* `P1` - P1\n* `P2` - P2\n* `P3` - P3\n* `P4` - P4'
        ),
})

/**
 * Remove the user's signal autonomy config, opting them out of autostart entirely. Unassigned tasks can still be picked up manually.
 * @summary Opt out of signal autostart
 */
export const UsersSignalAutonomyDestroyParams = /* @__PURE__ */ zod.object({
    user_id: zod
        .string()
        .describe(
            "PostHog user identifier. Pass `@me` to target the currently authenticated user. Staff users may pass another user's primary key."
        ),
})
