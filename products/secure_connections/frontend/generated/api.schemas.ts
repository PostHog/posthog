/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `not_configured` - not_configured
 * * `waiting` - waiting
 * * `connected` - connected
 */
export type SecureConnectionStateEnumApi =
    (typeof SecureConnectionStateEnumApi)[keyof typeof SecureConnectionStateEnumApi]

export const SecureConnectionStateEnumApi = {
    NotConfigured: 'not_configured',
    Waiting: 'waiting',
    Connected: 'connected',
} as const

export interface SecureConnectionApi {
    /** Stable identifier for this connection. */
    id: string
    /** Name advertised by the connection proxy. */
    name: string
    /** Type of service exposed by this connection. */
    connection_type: string
    /** Current status reported by the connection service. */
    connection_status: string
    /** How requests are selected by the customer-side proxy. */
    selector_kind: string
    /** Public routing selector advertised for this connection. */
    selector: string
}

export interface SecureConnectionStatusApi {
    /** Current setup state for this project's secure connection.
     *
     * * `not_configured` - not_configured
     * * `waiting` - waiting
     * * `connected` - connected */
    connection_state: SecureConnectionStateEnumApi
    /** Services currently advertised through the secure connection. */
    connections: SecureConnectionApi[]
}

export interface ErrorResponseApi {
    /** Error message */
    error: string
}

export interface SecureConnectionEnrollmentApi {
    /** One-time response credential used to enroll a connection proxy. */
    enrollment_key: string
    /** Tenant-scoped credential used by the proxy to report its available services. */
    advertisement_token: string
    /** Tenant identifier used by the connection proxy. */
    tenant_id: string
    /** Control server URL used by the connection proxy. */
    control_url: string
}

export type SecureConnectionApprovalsApiCdpApprovedConnections = { [key: string]: { [key: string]: unknown } }

export interface SecureConnectionApprovalsApi {
    cdp_approved_connections: SecureConnectionApprovalsApiCdpApprovedConnections
}

export interface SecureConnectionApprovalApi {
    connection_id: string
    approved: boolean
}

export interface SecureConnectionTestApi {
    /** Whether at least one active connection was found. */
    success: boolean
    /** Result of the connection check. */
    detail: string
}
