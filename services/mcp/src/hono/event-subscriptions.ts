import { ErrorCode } from '@modelcontextprotocol/sdk/types.js'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { McpEventSubscriptionsPreviewBody } from '@/generated/cdp/api'
import { hasScopes } from '@/lib/api'
import { PostHogApiError, PostHogPermissionError, PostHogRateLimitError, PostHogValidationError } from '@/lib/errors'
import type { RequestProperties } from '@/lib/request-properties'
import { EVENT_SUBSCRIPTION_SCOPES } from '@/tools/toolDefinitions'

import type { ResolvedState } from './request-state-resolver'
import { toMcpInputSchema } from './tool-catalog'

export const MCP_EVENT_NAME = 'posthog.event_captured'
export const MCP_EVENTS_GUIDANCE =
    'For captured-event subscriptions, choose an explicit project and normal destination filters. ' +
    'Before events/subscribe, use mcp-events-preview with the same arguments when available to validate filters and inspect matching examples. ' +
    'In exec mode, call that tool through exec. Backend validation still runs on every subscription. ' +
    'Use the client’s native event-triggered task or subscription interface. The events/subscribe protocol method is not an exec command or an ordinary MCP tool. ' +
    'Delivery includes future events only; missed events cannot be replayed.'

const generatedArguments = McpEventSubscriptionsPreviewBody()
const argumentsSchema = generatedArguments.extend({ filters: generatedArguments.shape.filters.strict() }).strict()
const deliveryIdentitySchema = z
    .object({
        mode: z.literal('webhook'),
        url: z.url().max(4096),
    })
    .strict()
const subscribeSchema = z
    .object({
        name: z.literal(MCP_EVENT_NAME),
        arguments: argumentsSchema,
        delivery: deliveryIdentitySchema.extend({ secret: z.string().max(128) }),
        ttlMs: z.number().int().min(1000).nullable().optional(),
        cursor: z.null().optional(),
        _meta: z.record(z.string(), z.unknown()).optional(),
    })
    .strict()
const unsubscribeSchema = z
    .object({
        name: z.literal(MCP_EVENT_NAME),
        arguments: argumentsSchema,
        delivery: deliveryIdentitySchema,
        _meta: z.record(z.string(), z.unknown()).optional(),
    })
    .strict()
const payloadSchema = z.object({
    event: z.string().describe('Original captured event name.'),
    distinct_id: z.string().describe('Distinct ID attached to the captured event.'),
    properties: z.record(z.string(), z.json()).describe('Event properties the subscriber is allowed to read.'),
}) satisfies z.ZodType<Schemas.MCPEventData>

export class McpEventRpcError extends Error {
    constructor(
        public readonly code: number,
        message: string,
        public readonly data?: Record<string, unknown>
    ) {
        super(message)
    }
}

export function eventsEnabled(state: ResolvedState): boolean {
    return state.toolFeatureFlags?.['mcp-events'] === true
}

export function canSubscribeToEvents(state: ResolvedState, props: RequestProperties): boolean {
    return eventsEnabled(state) && !props.readOnly && hasScopes(state.apiKeyScopes, [...EVENT_SUBSCRIPTION_SCOPES])
}

function parse<T extends z.ZodType>(schema: T, params: unknown): z.output<T> {
    const result = schema.safeParse(params)
    if (!result.success) {
        throw new McpEventRpcError(ErrorCode.InvalidParams, 'Invalid event subscription parameters.', {
            fields: result.error.issues.map((issue) => issue.path.join('.')),
        })
    }
    return result.data
}

function translateApiError(error: unknown): never {
    if (error instanceof PostHogRateLimitError) {
        throw new McpEventRpcError(
            -32000,
            'PostHog rate limited this subscription request. Retry after the indicated delay.',
            {
                retryAfterSeconds: error.retryAfterSeconds,
            }
        )
    }
    if (error instanceof PostHogValidationError) {
        if (error.attr === 'callback__reason') {
            throw new McpEventRpcError(-32015, 'Callback verification failed.', { reason: error.detail })
        }
        throw new McpEventRpcError(ErrorCode.InvalidParams, error.detail, { field: error.attr })
    }
    if (
        error instanceof PostHogPermissionError ||
        (error instanceof PostHogApiError && [401, 403, 404].includes(error.status))
    ) {
        throw new McpEventRpcError(-32001, 'This connection cannot access the requested event subscription.')
    }
    throw error
}

export class EventSubscriptions {
    list(state: ResolvedState, props: RequestProperties, params: unknown): { events: unknown[] } {
        parse(
            z
                .object({
                    cursor: z.null().optional(),
                    _meta: z.record(z.string(), z.unknown()).optional(),
                })
                .strict(),
            params ?? {}
        )
        if (!canSubscribeToEvents(state, props)) {
            return { events: [] }
        }
        return {
            events: [
                {
                    name: MCP_EVENT_NAME,
                    description:
                        'A captured PostHog event matching the subscribing account’s project and normal destination filters. ' +
                        MCP_EVENTS_GUIDANCE,
                    delivery: ['webhook'],
                    inputSchema: { ...toMcpInputSchema(argumentsSchema), additionalProperties: false },
                    payloadSchema: { ...toMcpInputSchema(payloadSchema), additionalProperties: false },
                },
            ],
        }
    }

    async subscribe(
        state: ResolvedState,
        props: RequestProperties,
        params: unknown
    ): Promise<{
        id: string
        refreshBefore: string
        cursor: null
        truncated: false
    }> {
        this.assertCanManage(state, props, true)
        const data = parse(subscribeSchema, params)
        try {
            const result = await state.context.api.request<Schemas.MCPEventSubscription>({
                method: 'POST',
                path: `/api/projects/${data.arguments.project_id}/mcp_event_subscriptions/subscribe/`,
                body: {
                    name: data.name,
                    arguments: data.arguments,
                    delivery: data.delivery,
                    ...(data.ttlMs !== undefined ? { ttl_ms: data.ttlMs } : {}),
                    cursor: data.cursor ?? null,
                },
            })
            return { id: result.id, refreshBefore: result.expires_at, cursor: null, truncated: false }
        } catch (error) {
            return translateApiError(error)
        }
    }

    async unsubscribe(state: ResolvedState, props: RequestProperties, params: unknown): Promise<Record<string, never>> {
        this.assertCanManage(state, props, false)
        const data = parse(unsubscribeSchema, params)
        try {
            await state.context.api.request({
                method: 'POST',
                path: `/api/projects/${data.arguments.project_id}/mcp_event_subscriptions/unsubscribe/`,
                body: { name: data.name, arguments: data.arguments, delivery: data.delivery },
            })
            return {}
        } catch (error) {
            return translateApiError(error)
        }
    }

    private assertCanManage(state: ResolvedState, props: RequestProperties, subscribe: boolean): void {
        const scopes = subscribe ? [...EVENT_SUBSCRIPTION_SCOPES] : ['mcp_event_subscription:write']
        if (props.readOnly || !hasScopes(state.apiKeyScopes, scopes)) {
            throw new McpEventRpcError(-32001, 'This connection needs permission to manage MCP event subscriptions.', {
                requiredScopes: scopes,
            })
        }
    }
}
