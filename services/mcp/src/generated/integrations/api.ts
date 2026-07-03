/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const IntegrationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const IntegrationsListQueryParams = /* @__PURE__ */ zod.object({
    kind: zod
        .enum([
            'anthropic',
            'apns',
            'aws-s3',
            'azure-blob',
            'bing-ads',
            'clickup',
            'customerio-app',
            'customerio-track',
            'customerio-webhook',
            'databricks',
            'email',
            'firebase',
            'github',
            'gitlab',
            'google-ads',
            'google-analytics',
            'google-cloud-service-account',
            'google-cloud-storage',
            'google-pubsub',
            'google-search-console',
            'google-sheets',
            'hubspot',
            'instagram',
            'intercom',
            'jira',
            'linear',
            'linkedin-ads',
            'meta-ads',
            'pinterest-ads',
            'postgresql',
            'reddit-ads',
            's3-compatible',
            'salesforce',
            'slack',
            'slack-posthog-code',
            'snapchat',
            'stripe',
            'tiktok-ads',
            'twilio',
            'vercel',
        ])
        .optional()
        .describe(
            '* `anthropic` - Anthropic\n* `apns` - Apple Push\n* `aws-s3` - Aws S3\n* `azure-blob` - Azure Blob\n* `bing-ads` - Bing Ads\n* `clickup` - Clickup\n* `customerio-app` - Customerio App\n* `customerio-track` - Customerio Track\n* `customerio-webhook` - Customerio Webhook\n* `databricks` - Databricks\n* `email` - Email\n* `firebase` - Firebase\n* `github` - Github\n* `gitlab` - Gitlab\n* `google-ads` - Google Ads\n* `google-analytics` - Google Analytics\n* `google-cloud-service-account` - Google Cloud Service Account\n* `google-cloud-storage` - Google Cloud Storage\n* `google-pubsub` - Google Pubsub\n* `google-search-console` - Google Search Console\n* `google-sheets` - Google Sheets\n* `hubspot` - Hubspot\n* `instagram` - Instagram\n* `intercom` - Intercom\n* `jira` - Jira\n* `linear` - Linear\n* `linkedin-ads` - Linkedin Ads\n* `meta-ads` - Meta Ads\n* `pinterest-ads` - Pinterest Ads\n* `postgresql` - Postgresql\n* `reddit-ads` - Reddit Ads\n* `s3-compatible` - S3 Compatible\n* `salesforce` - Salesforce\n* `slack` - Slack\n* `slack-posthog-code` - Slack Posthog Code\n* `snapchat` - Snapchat\n* `stripe` - Stripe\n* `tiktok-ads` - Tiktok Ads\n* `twilio` - Twilio\n* `vercel` - Vercel'
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const IntegrationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this integration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const IntegrationsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this integration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const IntegrationsChannelsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this integration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const integrationsChannelsRetrieveQueryLimitDefault = 50
export const integrationsChannelsRetrieveQueryLimitMax = 200

export const integrationsChannelsRetrieveQueryOffsetDefault = 0
export const integrationsChannelsRetrieveQueryOffsetMin = 0

export const integrationsChannelsRetrieveQuerySearchDefault = ``

export const IntegrationsChannelsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    limit: zod
        .number()
        .min(1)
        .max(integrationsChannelsRetrieveQueryLimitMax)
        .default(integrationsChannelsRetrieveQueryLimitDefault)
        .describe('Maximum number of channels to return per request (max 200).'),
    offset: zod
        .number()
        .min(integrationsChannelsRetrieveQueryOffsetMin)
        .default(integrationsChannelsRetrieveQueryOffsetDefault)
        .describe('Number of channels to skip before returning results.'),
    search: zod
        .string()
        .default(integrationsChannelsRetrieveQuerySearchDefault)
        .describe('Optional case-insensitive channel name or ID search query.'),
})

export const IntegrationsGithubReposRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this integration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const integrationsGithubReposRetrieveQueryLimitDefault = 100
export const integrationsGithubReposRetrieveQueryLimitMax = 500

export const integrationsGithubReposRetrieveQueryOffsetDefault = 0
export const integrationsGithubReposRetrieveQueryOffsetMin = 0

export const integrationsGithubReposRetrieveQuerySearchDefault = ``

export const IntegrationsGithubReposRetrieveQueryParams = /* @__PURE__ */ zod.object({
    limit: zod
        .number()
        .min(1)
        .max(integrationsGithubReposRetrieveQueryLimitMax)
        .default(integrationsGithubReposRetrieveQueryLimitDefault)
        .describe('Maximum number of repositories to return per request (max 500).'),
    offset: zod
        .number()
        .min(integrationsGithubReposRetrieveQueryOffsetMin)
        .default(integrationsGithubReposRetrieveQueryOffsetDefault)
        .describe('Number of repositories to skip before returning results.'),
    search: zod
        .string()
        .default(integrationsGithubReposRetrieveQuerySearchDefault)
        .describe('Optional case-insensitive repository name search query.'),
})

export const IntegrationsJiraProjectsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this integration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const IntegrationsLinearTeamsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this integration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
