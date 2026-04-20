// AUTO-GENERATED from products/signals/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    UsersSignalAutonomyDestroyParams,
    UsersSignalAutonomyRetrieveParams,
    UsersSignalAutonomyUpdateBody,
    UsersSignalAutonomyUpdateParams,
} from '@/generated/signals/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const SignalsAutostartGetSchema = UsersSignalAutonomyRetrieveParams.extend({
    user_id: UsersSignalAutonomyRetrieveParams.shape['user_id']
        .default('@me')
        .optional()
        .describe(
            "PostHog user identifier. Use `@me` to target the currently authenticated user; staff users can pass another user's primary key."
        ),
})

const signalsAutostartGet = (): ToolBase<typeof SignalsAutostartGetSchema, Schemas.SignalUserAutonomyConfig> => ({
    name: 'signals-autostart-get',
    schema: SignalsAutostartGetSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAutostartGetSchema>) => {
        const result = await context.api.request<Schemas.SignalUserAutonomyConfig>({
            method: 'GET',
            path: `/api/users/${encodeURIComponent(String(params.user_id))}/signal_autonomy/`,
        })
        return result
    },
})

const SignalsAutostartSetSchema = UsersSignalAutonomyUpdateParams.extend(UsersSignalAutonomyUpdateBody.shape).extend({
    user_id: UsersSignalAutonomyUpdateParams.shape['user_id']
        .default('@me')
        .optional()
        .describe(
            "PostHog user identifier. Use `@me` to target the currently authenticated user; staff users can pass another user's primary key."
        ),
})

const signalsAutostartSet = (): ToolBase<typeof SignalsAutostartSetSchema, Schemas.SignalUserAutonomyConfig> => ({
    name: 'signals-autostart-set',
    schema: SignalsAutostartSetSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAutostartSetSchema>) => {
        const body: Record<string, unknown> = {}
        if (params.autostart_priority !== undefined) {
            body['autostart_priority'] = params.autostart_priority
        }
        const result = await context.api.request<Schemas.SignalUserAutonomyConfig>({
            method: 'POST',
            path: `/api/users/${encodeURIComponent(String(params.user_id))}/signal_autonomy/`,
            body,
        })
        return result
    },
})

const SignalsAutostartRemoveSchema = UsersSignalAutonomyDestroyParams.extend({
    user_id: UsersSignalAutonomyDestroyParams.shape['user_id']
        .default('@me')
        .optional()
        .describe(
            "PostHog user identifier. Use `@me` to target the currently authenticated user; staff users can pass another user's primary key."
        ),
})

const signalsAutostartRemove = (): ToolBase<typeof SignalsAutostartRemoveSchema, unknown> => ({
    name: 'signals-autostart-remove',
    schema: SignalsAutostartRemoveSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAutostartRemoveSchema>) => {
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/users/${encodeURIComponent(String(params.user_id))}/signal_autonomy/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'signals-autostart-get': signalsAutostartGet,
    'signals-autostart-set': signalsAutostartSet,
    'signals-autostart-remove': signalsAutostartRemove,
}
