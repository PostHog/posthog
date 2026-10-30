/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export type MCPEventFiltersApiActionsItem = { [key: string]: unknown }

export type MCPEventFiltersApiEventsItem = { [key: string]: unknown }

export type MCPEventFiltersApiPropertiesItem = { [key: string]: unknown }

export interface MCPEventFiltersApi {
    /** Captured PostHog events. Use events. */
    source?: string
    /** Saved action entries combined with the event entries using OR. Example: [{"id": "123", "type": "actions"}]. */
    actions?: MCPEventFiltersApiActionsItem[]
    /** Captured event entries combined with OR. Example: [{"id": "survey sent", "type": "events", "properties": [{"key": "rating", "type": "event", "operator": "lt", "value": 3}]}]. */
    events?: MCPEventFiltersApiEventsItem[]
    /** Property conditions applied to all selected events. Example: [{"key": "plan", "type": "event", "operator": "exact", "value": "enterprise"}]. */
    properties?: MCPEventFiltersApiPropertiesItem[]
    /** Apply the project's existing test-account exclusions. */
    filter_test_accounts?: boolean
}

export interface MCPEventArgumentsApi {
    /**
     * Project whose captured events should be monitored.
     * @minimum 1
     */
    project_id: number
    /** Normal real-time destination filters. Preview the filters before subscribing. */
    filters: MCPEventFiltersApi
}

export interface MCPEventSubscriptionApi {
    /** Subscription ID supplied to the receiving MCP client. */
    readonly id: string
    /** Project and event filters. */
    readonly arguments: MCPEventArgumentsApi
    /** Callback hostname. Paths and signing secrets are hidden. */
    readonly callback_host: string
    /** Time when this subscription stops delivering events. */
    readonly expires_at: string
    /** Whether this subscription is enabled. */
    readonly active: boolean
    /** Time when this subscription was created. */
    readonly created_at: string
}

export interface PaginatedMCPEventSubscriptionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPEventSubscriptionApi[]
}

/**
 * * `posthog.event_captured` - posthog.event_captured
 */
export type MCPEventEnvelopeNameEnumApi = (typeof MCPEventEnvelopeNameEnumApi)[keyof typeof MCPEventEnvelopeNameEnumApi]

export const MCPEventEnvelopeNameEnumApi = {
    PosthogeventCaptured: 'posthog.event_captured',
} as const

/**
 * Event properties the subscriber is allowed to read.
 */
export type MCPEventDataApiProperties = {
    [key: string]: string | number | boolean | { [key: string]: unknown } | unknown[] | null
}

export interface MCPEventDataApi {
    /** Event properties the subscriber is allowed to read. */
    properties: MCPEventDataApiProperties
    /** Original captured event name. */
    event: string
    /** Distinct ID attached to the captured event. */
    distinct_id: string
}

export interface MCPEventEnvelopeApi {
    /** Event occurrence time, including its timezone. */
    timestamp: string
    /** Null because replay is unavailable. */
    cursor: unknown
    /**
     * Stable source event ID used to deduplicate deliveries.
     * @minLength 1
     * @maxLength 255
     */
    eventId: string
    /** Subscribed MCP event type.
     *
     * * `posthog.event_captured` - posthog.event_captured */
    name: MCPEventEnvelopeNameEnumApi
    /** Captured event data. */
    data: MCPEventDataApi
}

export interface MCPEventPreviewApi {
    /** Normalized filters the subscription would use. */
    readonly filters: MCPEventFiltersApi
    /** Up to five matching events from the lookback window. */
    examples: MCPEventEnvelopeApi[]
    /** Number of days searched for examples. */
    lookback_days: number
    /** Maximum number of examples. This is not a total event count. */
    sample_limit: number
}

export interface MCPEventWebhookApi {
    /** Delivery mode. Use webhook. */
    mode: string
    /**
     * HTTPS callback supplied by the receiving MCP client.
     * @maxLength 4096
     */
    url: string
    /**
     * Client-supplied whsec_ signing secret.
     * @maxLength 128
     */
    secret: string
}

export interface MCPEventSubscribeApi {
    /** Event type. Use posthog.event_captured. */
    name: string
    /** Project and event filters for this subscription. */
    arguments: MCPEventArgumentsApi
    /** Callback and signing information supplied by the client. */
    delivery: MCPEventWebhookApi
    /**
     * Requested lifetime in milliseconds. The server grants a finite lifetime of at most 24 hours.
     * @minimum 1000
     * @nullable
     */
    ttl_ms?: number | null
    /**
     * Replay is unavailable. Use null to receive future events.
     * @nullable
     */
    cursor?: string | null
}

export interface MCPEventIdentityArgumentsApi {
    /**
     * Project whose captured events should be monitored.
     * @minimum 1
     */
    project_id: number
    /** Original event filters, including filters for deleted resources. */
    filters: MCPEventFiltersApi
}

export interface MCPEventUnsubscribeDeliveryApi {
    /** Delivery mode. Use webhook. */
    mode: string
    /**
     * Original callback URL supplied when subscribing.
     * @maxLength 4096
     */
    url: string
}

export interface MCPEventUnsubscribeApi {
    /** Event type. Use posthog.event_captured. */
    name: string
    /** Original project and event filters. */
    arguments: MCPEventIdentityArgumentsApi
    /** Original callback identity. */
    delivery: MCPEventUnsubscribeDeliveryApi
}

export type McpEventSubscriptionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
