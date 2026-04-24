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

/**
 * ViewSet for organization-level integrations.

Provides access to integrations that are scoped to the entire organization
(vs. project-level integrations). Examples include Vercel, AWS Marketplace, etc.

Creation is handled by the integration installation flows
(e.g., Vercel marketplace installation). Users can disconnect integrations
via the DELETE endpoint.
 */
export const IntegrationsEnvironmentMappingPartialUpdateBody = /* @__PURE__ */ zod
    .object({})
    .describe('Serializer for organization-level integrations.')

export const roleExternalReferencesCreateBodyProviderMax = 32

export const roleExternalReferencesCreateBodyProviderOrganizationIdMax = 255

export const roleExternalReferencesCreateBodyProviderRoleIdMax = 255

export const roleExternalReferencesCreateBodyProviderRoleSlugMax = 255

export const roleExternalReferencesCreateBodyProviderRoleNameMax = 255

export const RoleExternalReferencesCreateBody = /* @__PURE__ */ zod.object({
    provider: zod
        .string()
        .max(roleExternalReferencesCreateBodyProviderMax)
        .describe('Integration kind (e.g., github, linear, jira, slack).'),
    provider_organization_id: zod
        .string()
        .max(roleExternalReferencesCreateBodyProviderOrganizationIdMax)
        .describe('Provider organization/workspace/site identifier.'),
    provider_role_id: zod
        .string()
        .max(roleExternalReferencesCreateBodyProviderRoleIdMax)
        .describe('Stable provider role identifier.'),
    provider_role_slug: zod
        .string()
        .max(roleExternalReferencesCreateBodyProviderRoleSlugMax)
        .nullish()
        .describe('Human-friendly provider role identifier.'),
    provider_role_name: zod
        .string()
        .max(roleExternalReferencesCreateBodyProviderRoleNameMax)
        .describe('Display name of the provider role.'),
    role: zod.uuid().describe('PostHog role UUID this external role maps to.'),
})

export const IntegrationsCreateBody = /* @__PURE__ */ zod
    .object({
        kind: zod
            .enum([
                'slack',
                'slack-posthog-code',
                'salesforce',
                'hubspot',
                'google-pubsub',
                'google-cloud-storage',
                'google-ads',
                'google-sheets',
                'google-cloud-service-account',
                'snapchat',
                'linkedin-ads',
                'reddit-ads',
                'tiktok-ads',
                'bing-ads',
                'intercom',
                'email',
                'linear',
                'github',
                'gitlab',
                'meta-ads',
                'twilio',
                'clickup',
                'vercel',
                'databricks',
                'azure-blob',
                'firebase',
                'jira',
                'pinterest-ads',
                'stripe',
                'customerio-app',
                'customerio-webhook',
                'customerio-track',
            ])
            .describe(
                '* `slack` - Slack\n* `slack-posthog-code` - Slack Posthog Code\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `google-cloud-service-account` - Google Cloud Service Account\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira\n* `pinterest-ads` - Pinterest Ads\n* `stripe` - Stripe\n* `customerio-app` - Customerio App\n* `customerio-webhook` - Customerio Webhook\n* `customerio-track` - Customerio Track'
            ),
        config: zod.unknown().optional(),
    })
    .describe('Standard Integration serializer.')

export const IntegrationsEmailPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        kind: zod
            .enum([
                'slack',
                'slack-posthog-code',
                'salesforce',
                'hubspot',
                'google-pubsub',
                'google-cloud-storage',
                'google-ads',
                'google-sheets',
                'google-cloud-service-account',
                'snapchat',
                'linkedin-ads',
                'reddit-ads',
                'tiktok-ads',
                'bing-ads',
                'intercom',
                'email',
                'linear',
                'github',
                'gitlab',
                'meta-ads',
                'twilio',
                'clickup',
                'vercel',
                'databricks',
                'azure-blob',
                'firebase',
                'jira',
                'pinterest-ads',
                'stripe',
                'customerio-app',
                'customerio-webhook',
                'customerio-track',
            ])
            .optional()
            .describe(
                '* `slack` - Slack\n* `slack-posthog-code` - Slack Posthog Code\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `google-cloud-service-account` - Google Cloud Service Account\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira\n* `pinterest-ads` - Pinterest Ads\n* `stripe` - Stripe\n* `customerio-app` - Customerio App\n* `customerio-webhook` - Customerio Webhook\n* `customerio-track` - Customerio Track'
            ),
        config: zod.unknown().optional(),
    })
    .describe('Standard Integration serializer.')

export const IntegrationsEmailVerifyCreateBody = /* @__PURE__ */ zod
    .object({
        kind: zod
            .enum([
                'slack',
                'slack-posthog-code',
                'salesforce',
                'hubspot',
                'google-pubsub',
                'google-cloud-storage',
                'google-ads',
                'google-sheets',
                'google-cloud-service-account',
                'snapchat',
                'linkedin-ads',
                'reddit-ads',
                'tiktok-ads',
                'bing-ads',
                'intercom',
                'email',
                'linear',
                'github',
                'gitlab',
                'meta-ads',
                'twilio',
                'clickup',
                'vercel',
                'databricks',
                'azure-blob',
                'firebase',
                'jira',
                'pinterest-ads',
                'stripe',
                'customerio-app',
                'customerio-webhook',
                'customerio-track',
            ])
            .describe(
                '* `slack` - Slack\n* `slack-posthog-code` - Slack Posthog Code\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `google-cloud-service-account` - Google Cloud Service Account\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira\n* `pinterest-ads` - Pinterest Ads\n* `stripe` - Stripe\n* `customerio-app` - Customerio App\n* `customerio-webhook` - Customerio Webhook\n* `customerio-track` - Customerio Track'
            ),
        config: zod.unknown().optional(),
    })
    .describe('Standard Integration serializer.')

/**
 * Unified endpoint for generating Domain Connect apply URLs.

Accepts a context ("email" or "proxy") and the relevant resource ID.
The backend resolves the domain, template variables, and service ID
based on context, then builds the signed apply URL.
 */
export const IntegrationsDomainConnectApplyUrlCreateBody = /* @__PURE__ */ zod
    .object({
        kind: zod
            .enum([
                'slack',
                'slack-posthog-code',
                'salesforce',
                'hubspot',
                'google-pubsub',
                'google-cloud-storage',
                'google-ads',
                'google-sheets',
                'google-cloud-service-account',
                'snapchat',
                'linkedin-ads',
                'reddit-ads',
                'tiktok-ads',
                'bing-ads',
                'intercom',
                'email',
                'linear',
                'github',
                'gitlab',
                'meta-ads',
                'twilio',
                'clickup',
                'vercel',
                'databricks',
                'azure-blob',
                'firebase',
                'jira',
                'pinterest-ads',
                'stripe',
                'customerio-app',
                'customerio-webhook',
                'customerio-track',
            ])
            .describe(
                '* `slack` - Slack\n* `slack-posthog-code` - Slack Posthog Code\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `google-cloud-service-account` - Google Cloud Service Account\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira\n* `pinterest-ads` - Pinterest Ads\n* `stripe` - Stripe\n* `customerio-app` - Customerio App\n* `customerio-webhook` - Customerio Webhook\n* `customerio-track` - Customerio Track'
            ),
        config: zod.unknown().optional(),
    })
    .describe('Standard Integration serializer.')
