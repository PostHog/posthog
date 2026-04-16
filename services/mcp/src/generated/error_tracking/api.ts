/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 4 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const ErrorTrackingIssuesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ErrorTrackingIssuesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesPartialUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}).optional(),
    assignee: zod
        .object({
            id: zod.union([zod.number(), zod.string()]).nullish(),
            type: zod.string().optional(),
        })
        .optional(),
    external_issues: zod
        .array(
            zod.object({
                external_url: zod.string(),
                id: zod.string(),
                integration: zod.object({
                    display_name: zod.string(),
                    id: zod.number(),
                    kind: zod.enum([
                        'slack',
                        'slack-posthog-code',
                        'salesforce',
                        'hubspot',
                        'google-pubsub',
                        'google-cloud-service-account',
                        'google-cloud-storage',
                        'google-ads',
                        'google-sheets',
                        'linkedin-ads',
                        'snapchat',
                        'intercom',
                        'email',
                        'twilio',
                        'linear',
                        'github',
                        'gitlab',
                        'meta-ads',
                        'clickup',
                        'reddit-ads',
                        'databricks',
                        'tiktok-ads',
                        'bing-ads',
                        'vercel',
                        'azure-blob',
                        'firebase',
                        'jira',
                        'pinterest-ads',
                        'customerio-app',
                        'customerio-webhook',
                        'customerio-track',
                    ]),
                }),
            })
        )
        .optional(),
})

export const ErrorTrackingIssuesMergeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesMergeCreateBody = /* @__PURE__ */ zod.object({
    ids: zod.array(zod.string()).describe('IDs of the issues to merge into the current issue.'),
})
