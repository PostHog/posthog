/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List all reverse proxies configured for the organization. Returns proxy records along with the maximum number allowed by the current plan.
 */
export const ProxyRecordsListParams = zod.object({
    organization_id: zod.string(),
})

export const ProxyRecordsListResponseItem = zod.object({
    results: zod.array(
        zod.object({
            id: zod.string().describe('Unique identifier for the proxy record.'),
            domain: zod
                .string()
                .describe(
                    "The custom domain to proxy through, e.g. 'e.example.com'. Must be a valid subdomain you control."
                ),
            target_cname: zod
                .string()
                .describe(
                    "The CNAME target to add as a DNS record for your domain. Point your domain's CNAME to this value."
                ),
            status: zod
                .enum(['waiting', 'issuing', 'valid', 'warning', 'erroring', 'deleting', 'timed_out'])
                .describe(
                    '* `waiting` - Waiting\n* `issuing` - Issuing\n* `valid` - Valid\n* `warning` - Warning\n* `erroring` - Erroring\n* `deleting` - Deleting\n* `timed_out` - Timed Out'
                )
                .describe(
                    'Current provisioning status. Values: waiting (DNS verification pending), issuing (SSL certificate being issued), valid (proxy is live and working), warning (proxy has issues but is operational), erroring (proxy setup failed), deleting (removal in progress), timed_out (DNS verification timed out).\n\n* `waiting` - Waiting\n* `issuing` - Issuing\n* `valid` - Valid\n* `warning` - Warning\n* `erroring` - Erroring\n* `deleting` - Deleting\n* `timed_out` - Timed Out'
                ),
            message: zod
                .string()
                .nullable()
                .describe('Human-readable status message with details about errors or warnings, if any.'),
            created_at: zod.string().datetime({}).describe('When this proxy record was created.'),
            updated_at: zod.string().datetime({}).describe('When this proxy record was last updated.'),
            created_by: zod.number().describe('ID of the user who created this proxy record.'),
        })
    ),
    max_proxy_records: zod
        .number()
        .describe("Maximum number of proxy records allowed for this organization's current plan."),
})
export const ProxyRecordsListResponse = zod.array(ProxyRecordsListResponseItem)

/**
 * Create a new managed reverse proxy. Provide the domain you want to proxy through. The response includes the CNAME target you need to add as a DNS record. Once the CNAME is configured, the proxy will be automatically verified and provisioned.
 */
export const ProxyRecordsCreateParams = zod.object({
    organization_id: zod.string(),
})

export const ProxyRecordsCreateBody = zod.object({
    domain: zod
        .string()
        .describe("The custom domain to proxy through, e.g. 'e.example.com'. Must be a valid subdomain you control."),
})

/**
 * Get details of a specific reverse proxy by ID. Returns the full configuration including domain, CNAME target, and current provisioning status.
 */
export const ProxyRecordsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this proxy record.'),
    organization_id: zod.string(),
})

export const ProxyRecordsRetrieveResponse = zod.object({
    id: zod.string().describe('Unique identifier for the proxy record.'),
    domain: zod
        .string()
        .describe("The custom domain to proxy through, e.g. 'e.example.com'. Must be a valid subdomain you control."),
    target_cname: zod
        .string()
        .describe("The CNAME target to add as a DNS record for your domain. Point your domain's CNAME to this value."),
    status: zod
        .enum(['waiting', 'issuing', 'valid', 'warning', 'erroring', 'deleting', 'timed_out'])
        .describe(
            '* `waiting` - Waiting\n* `issuing` - Issuing\n* `valid` - Valid\n* `warning` - Warning\n* `erroring` - Erroring\n* `deleting` - Deleting\n* `timed_out` - Timed Out'
        )
        .describe(
            'Current provisioning status. Values: waiting (DNS verification pending), issuing (SSL certificate being issued), valid (proxy is live and working), warning (proxy has issues but is operational), erroring (proxy setup failed), deleting (removal in progress), timed_out (DNS verification timed out).\n\n* `waiting` - Waiting\n* `issuing` - Issuing\n* `valid` - Valid\n* `warning` - Warning\n* `erroring` - Erroring\n* `deleting` - Deleting\n* `timed_out` - Timed Out'
        ),
    message: zod
        .string()
        .nullable()
        .describe('Human-readable status message with details about errors or warnings, if any.'),
    created_at: zod.string().datetime({}).describe('When this proxy record was created.'),
    updated_at: zod.string().datetime({}).describe('When this proxy record was last updated.'),
    created_by: zod.number().describe('ID of the user who created this proxy record.'),
})

/**
 * Delete a reverse proxy. For proxies in 'waiting', 'erroring', or 'timed_out' status, the record is deleted immediately. For active proxies, a deletion workflow is started to clean up the provisioned infrastructure.
 */
export const ProxyRecordsDestroyParams = zod.object({
    id: zod.string().describe('A UUID string identifying this proxy record.'),
    organization_id: zod.string(),
})

/**
 * Retry provisioning a failed reverse proxy. Only available for proxies in 'erroring' or 'timed_out' status. Resets the proxy to 'waiting' status and restarts the provisioning workflow.
 */
export const ProxyRecordsRetryCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this proxy record.'),
    organization_id: zod.string(),
})

export const ProxyRecordsRetryCreateResponse = zod.object({
    id: zod.string().describe('Unique identifier for the proxy record.'),
    domain: zod
        .string()
        .describe("The custom domain to proxy through, e.g. 'e.example.com'. Must be a valid subdomain you control."),
    target_cname: zod
        .string()
        .describe("The CNAME target to add as a DNS record for your domain. Point your domain's CNAME to this value."),
    status: zod
        .enum(['waiting', 'issuing', 'valid', 'warning', 'erroring', 'deleting', 'timed_out'])
        .describe(
            '* `waiting` - Waiting\n* `issuing` - Issuing\n* `valid` - Valid\n* `warning` - Warning\n* `erroring` - Erroring\n* `deleting` - Deleting\n* `timed_out` - Timed Out'
        )
        .describe(
            'Current provisioning status. Values: waiting (DNS verification pending), issuing (SSL certificate being issued), valid (proxy is live and working), warning (proxy has issues but is operational), erroring (proxy setup failed), deleting (removal in progress), timed_out (DNS verification timed out).\n\n* `waiting` - Waiting\n* `issuing` - Issuing\n* `valid` - Valid\n* `warning` - Warning\n* `erroring` - Erroring\n* `deleting` - Deleting\n* `timed_out` - Timed Out'
        ),
    message: zod
        .string()
        .nullable()
        .describe('Human-readable status message with details about errors or warnings, if any.'),
    created_at: zod.string().datetime({}).describe('When this proxy record was created.'),
    updated_at: zod.string().datetime({}).describe('When this proxy record was last updated.'),
    created_by: zod.number().describe('ID of the user who created this proxy record.'),
})
