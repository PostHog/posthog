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

export const mcpEventSubscriptionsPreviewBodyFiltersOneSourceDefault = `events`

export const McpEventSubscriptionsPreviewBody = /* @__PURE__ */ zod.object({
    project_id: zod.number().min(1).describe('Project whose captured events should be monitored.'),
    filters: zod
        .object({
            source: zod
                .string()
                .default(mcpEventSubscriptionsPreviewBodyFiltersOneSourceDefault)
                .describe('Captured PostHog events. Use events.'),
            actions: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .optional()
                .describe(
                    'Saved action entries combined with the event entries using OR. Example: [{\"id\": \"123\", \"type\": \"actions\"}].'
                ),
            events: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .optional()
                .describe(
                    'Captured event entries combined with OR. Example: [{\"id\": \"survey sent\", \"type\": \"events\", \"properties\": [{\"key\": \"rating\", \"type\": \"event\", \"operator\": \"lt\", \"value\": 3}]}].'
                ),
            properties: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .optional()
                .describe(
                    'Property conditions applied to all selected events. Example: [{\"key\": \"plan\", \"type\": \"event\", \"operator\": \"exact\", \"value\": \"enterprise\"}].'
                ),
            filter_test_accounts: zod
                .boolean()
                .optional()
                .describe("Apply the project's existing test-account exclusions."),
        })
        .describe('Normal real-time destination filters. Preview the filters before subscribing.'),
})

export const mcpEventSubscriptionsSubscribeCreateBodyArgumentsOneFiltersOneSourceDefault = `events`
export const mcpEventSubscriptionsSubscribeCreateBodyDeliveryOneUrlMax = 4096

export const mcpEventSubscriptionsSubscribeCreateBodyDeliveryOneSecretMax = 128

export const mcpEventSubscriptionsSubscribeCreateBodyTtlMsDefault = 86400000
export const mcpEventSubscriptionsSubscribeCreateBodyTtlMsMin = 1000

export const McpEventSubscriptionsSubscribeCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().describe('Event type. Use posthog.event_captured.'),
    arguments: zod
        .object({
            project_id: zod.number().min(1).describe('Project whose captured events should be monitored.'),
            filters: zod
                .object({
                    source: zod
                        .string()
                        .default(mcpEventSubscriptionsSubscribeCreateBodyArgumentsOneFiltersOneSourceDefault)
                        .describe('Captured PostHog events. Use events.'),
                    actions: zod
                        .array(zod.record(zod.string(), zod.unknown()))
                        .optional()
                        .describe(
                            'Saved action entries combined with the event entries using OR. Example: [{\"id\": \"123\", \"type\": \"actions\"}].'
                        ),
                    events: zod
                        .array(zod.record(zod.string(), zod.unknown()))
                        .optional()
                        .describe(
                            'Captured event entries combined with OR. Example: [{\"id\": \"survey sent\", \"type\": \"events\", \"properties\": [{\"key\": \"rating\", \"type\": \"event\", \"operator\": \"lt\", \"value\": 3}]}].'
                        ),
                    properties: zod
                        .array(zod.record(zod.string(), zod.unknown()))
                        .optional()
                        .describe(
                            'Property conditions applied to all selected events. Example: [{\"key\": \"plan\", \"type\": \"event\", \"operator\": \"exact\", \"value\": \"enterprise\"}].'
                        ),
                    filter_test_accounts: zod
                        .boolean()
                        .optional()
                        .describe("Apply the project's existing test-account exclusions."),
                })
                .describe('Normal real-time destination filters. Preview the filters before subscribing.'),
        })
        .describe('Project and event filters for this subscription.'),
    delivery: zod
        .object({
            mode: zod.string().describe('Delivery mode. Use webhook.'),
            url: zod
                .url()
                .max(mcpEventSubscriptionsSubscribeCreateBodyDeliveryOneUrlMax)
                .describe('HTTPS callback supplied by the receiving MCP client.'),
            secret: zod
                .string()
                .max(mcpEventSubscriptionsSubscribeCreateBodyDeliveryOneSecretMax)
                .describe('Client-supplied whsec_ signing secret.'),
        })
        .describe('Callback and signing information supplied by the client.'),
    ttl_ms: zod
        .number()
        .min(mcpEventSubscriptionsSubscribeCreateBodyTtlMsMin)
        .nullish()
        .default(mcpEventSubscriptionsSubscribeCreateBodyTtlMsDefault)
        .describe('Requested lifetime in milliseconds. The server grants a finite lifetime of at most 24 hours.'),
    cursor: zod.string().nullish().describe('Replay is unavailable. Use null to receive future events.'),
})

export const mcpEventSubscriptionsUnsubscribeCreateBodyArgumentsOneFiltersOneSourceDefault = `events`
export const mcpEventSubscriptionsUnsubscribeCreateBodyDeliveryOneUrlMax = 4096

export const McpEventSubscriptionsUnsubscribeCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().describe('Event type. Use posthog.event_captured.'),
    arguments: zod
        .object({
            project_id: zod.number().min(1).describe('Project whose captured events should be monitored.'),
            filters: zod
                .object({
                    source: zod
                        .string()
                        .default(mcpEventSubscriptionsUnsubscribeCreateBodyArgumentsOneFiltersOneSourceDefault)
                        .describe('Captured PostHog events. Use events.'),
                    actions: zod
                        .array(zod.record(zod.string(), zod.unknown()))
                        .optional()
                        .describe(
                            'Saved action entries combined with the event entries using OR. Example: [{\"id\": \"123\", \"type\": \"actions\"}].'
                        ),
                    events: zod
                        .array(zod.record(zod.string(), zod.unknown()))
                        .optional()
                        .describe(
                            'Captured event entries combined with OR. Example: [{\"id\": \"survey sent\", \"type\": \"events\", \"properties\": [{\"key\": \"rating\", \"type\": \"event\", \"operator\": \"lt\", \"value\": 3}]}].'
                        ),
                    properties: zod
                        .array(zod.record(zod.string(), zod.unknown()))
                        .optional()
                        .describe(
                            'Property conditions applied to all selected events. Example: [{\"key\": \"plan\", \"type\": \"event\", \"operator\": \"exact\", \"value\": \"enterprise\"}].'
                        ),
                    filter_test_accounts: zod
                        .boolean()
                        .optional()
                        .describe("Apply the project's existing test-account exclusions."),
                })
                .describe('Original event filters, including filters for deleted resources.'),
        })
        .describe('Original project and event filters.'),
    delivery: zod
        .object({
            mode: zod.string().describe('Delivery mode. Use webhook.'),
            url: zod
                .url()
                .max(mcpEventSubscriptionsUnsubscribeCreateBodyDeliveryOneUrlMax)
                .describe('Original callback URL supplied when subscribing.'),
        })
        .describe('Original callback identity.'),
})
