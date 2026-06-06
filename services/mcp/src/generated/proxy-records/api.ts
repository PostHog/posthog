/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List all reverse proxies configured for the organization. Returns proxy records along with the maximum number allowed by the current plan.
 */
export const ProxyRecordsListParams = /* @__PURE__ */ zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/."
        ),
})

/**
 * Create a new managed reverse proxy. Provide the domain you want to proxy through. The response includes the CNAME target you need to add as a DNS record. Once the CNAME is configured, the proxy will be automatically verified and provisioned.
 */
export const ProxyRecordsCreateParams = /* @__PURE__ */ zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/."
        ),
})

export const ProxyRecordsCreateBody = /* @__PURE__ */ zod.object({
    domain: zod
        .string()
        .describe("The custom domain to proxy through, e.g. 'e.example.com'. Must be a valid subdomain you control."),
})

/**
 * Get details of a specific reverse proxy by ID. Returns the full configuration including domain, CNAME target, and current provisioning status.
 */
export const ProxyRecordsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this proxy record.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/."
        ),
})

/**
 * Delete a reverse proxy. For proxies in 'waiting', 'erroring', or 'timed_out' status, the record is deleted immediately. For active proxies, a deletion workflow is started to clean up the provisioned infrastructure.
 */
export const ProxyRecordsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this proxy record.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/."
        ),
})

/**
 * Run a deep diagnostic on a reverse proxy. Inspects DNS CNAME alignment, the certificate provider's hostname state, CAA records walked up the customer's DNS tree, HTTP-01 challenge reachability, a live event probe, and certificate expiry. Returns a structured report with each check's status and concrete remediation steps (e.g. exact DNS records to add). Use this to debug why a proxy is stuck or erroring.
 */
export const ProxyRecordsDiagnoseCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this proxy record.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/."
        ),
})

/**
 * Retry provisioning a failed reverse proxy. Only available for proxies in 'erroring' or 'timed_out' status. Resets the proxy to 'waiting' status and restarts the provisioning workflow.
 */
export const ProxyRecordsRetryCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this proxy record.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/."
        ),
})
