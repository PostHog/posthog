/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const ConnectionStateEnumApi = zod
    .enum(['not_configured', 'waiting', 'connected'])
    .describe('\* `not_configured` - not_configured\n\* `waiting` - waiting\n\* `connected` - connected')

export type ConnectionStateEnumApi = zod.input<typeof ConnectionStateEnumApi>
export type ConnectionStateEnumApiOutput = zod.output<typeof ConnectionStateEnumApi>

export const SecureConnectionApi = zod.object({
    id: zod.uuid().describe('Stable identifier for this connection.'),
    name: zod.string().describe('Name advertised by the connection proxy.'),
    connection_type: zod.string().describe('Type of service exposed by this connection.'),
    connection_status: zod.string().describe('Current status reported by the connection service.'),
})

export type SecureConnectionApi = zod.input<typeof SecureConnectionApi>
export type SecureConnectionApiOutput = zod.output<typeof SecureConnectionApi>

export const SecureConnectionStatusApi = zod.object({
    connection_state: zod
        .enum(['not_configured', 'waiting', 'connected'])
        .describe('\* `not_configured` - not_configured\n\* `waiting` - waiting\n\* `connected` - connected')
        .describe(
            "Current setup state for this project's secure connection.\n\n\* `not_configured` - not_configured\n\* `waiting` - waiting\n\* `connected` - connected"
        ),
    connections: zod
        .array(
            zod.object({
                id: zod.uuid().describe('Stable identifier for this connection.'),
                name: zod.string().describe('Name advertised by the connection proxy.'),
                connection_type: zod.string().describe('Type of service exposed by this connection.'),
                connection_status: zod.string().describe('Current status reported by the connection service.'),
            })
        )
        .describe('Services currently advertised through the secure connection.'),
})

export type SecureConnectionStatusApi = zod.input<typeof SecureConnectionStatusApi>
export type SecureConnectionStatusApiOutput = zod.output<typeof SecureConnectionStatusApi>

export const ErrorResponseApi = zod.object({
    error: zod.string().describe('Error message'),
})

export type ErrorResponseApi = zod.input<typeof ErrorResponseApi>
export type ErrorResponseApiOutput = zod.output<typeof ErrorResponseApi>

export const SecureConnectionEnrollmentApi = zod.object({
    enrollment_key: zod.string().describe('One-time response credential used to enroll a connection proxy.'),
    advertisement_token: zod
        .string()
        .describe('Tenant-scoped credential used by the proxy to report its available services.'),
    tenant_id: zod.uuid().describe('Tenant identifier used by the connection proxy.'),
    control_url: zod.url().describe('Control server URL used by the connection proxy.'),
})

export type SecureConnectionEnrollmentApi = zod.input<typeof SecureConnectionEnrollmentApi>
export type SecureConnectionEnrollmentApiOutput = zod.output<typeof SecureConnectionEnrollmentApi>

export const SecureConnectionTestApi = zod.object({
    success: zod.boolean().describe('Whether at least one active connection was found.'),
    detail: zod.string().describe('Result of the connection check.'),
})

export type SecureConnectionTestApi = zod.input<typeof SecureConnectionTestApi>
export type SecureConnectionTestApiOutput = zod.output<typeof SecureConnectionTestApi>
