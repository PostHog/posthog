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
 *
 * Provides access to integrations that are scoped to the entire organization
 * (vs. project-level integrations). Examples include Vercel, AWS Marketplace, etc.
 *
 * Creation is handled by the integration installation flows
 * (e.g., Vercel marketplace installation). Users can disconnect integrations
 * via the DELETE endpoint.
 */
export const IntegrationsEnvironmentMappingPartialUpdateBody = /* @__PURE__ */ zod
    .looseObject({})
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
        .describe('Provider organization\/workspace\/site identifier.'),
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
                'snowflake',
                'stripe',
                'tiktok-ads',
                'twilio',
                'vercel',
            ])
            .describe(
                '\* `anthropic` - Anthropic\n\* `apns` - Apple Push\n\* `aws-s3` - Aws S3\n\* `azure-blob` - Azure Blob\n\* `bing-ads` - Bing Ads\n\* `clickup` - Clickup\n\* `customerio-app` - Customerio App\n\* `customerio-track` - Customerio Track\n\* `customerio-webhook` - Customerio Webhook\n\* `databricks` - Databricks\n\* `email` - Email\n\* `firebase` - Firebase\n\* `github` - Github\n\* `gitlab` - Gitlab\n\* `google-ads` - Google Ads\n\* `google-analytics` - Google Analytics\n\* `google-cloud-service-account` - Google Cloud Service Account\n\* `google-cloud-storage` - Google Cloud Storage\n\* `google-pubsub` - Google Pubsub\n\* `google-search-console` - Google Search Console\n\* `google-sheets` - Google Sheets\n\* `hubspot` - Hubspot\n\* `intercom` - Intercom\n\* `jira` - Jira\n\* `linear` - Linear\n\* `linkedin-ads` - Linkedin Ads\n\* `meta-ads` - Meta Ads\n\* `pinterest-ads` - Pinterest Ads\n\* `postgresql` - Postgresql\n\* `reddit-ads` - Reddit Ads\n\* `s3-compatible` - S3 Compatible\n\* `salesforce` - Salesforce\n\* `slack` - Slack\n\* `slack-posthog-code` - Slack Posthog Code\n\* `snapchat` - Snapchat\n\* `snowflake` - Snowflake\n\* `stripe` - Stripe\n\* `tiktok-ads` - Tiktok Ads\n\* `twilio` - Twilio\n\* `vercel` - Vercel'
            ),
        config: zod.unknown().optional(),
    })
    .describe('Standard Integration serializer.')

export const IntegrationsEmailPartialUpdateBody = /* @__PURE__ */ zod
    .object({
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
                'snowflake',
                'stripe',
                'tiktok-ads',
                'twilio',
                'vercel',
            ])
            .optional()
            .describe(
                '\* `anthropic` - Anthropic\n\* `apns` - Apple Push\n\* `aws-s3` - Aws S3\n\* `azure-blob` - Azure Blob\n\* `bing-ads` - Bing Ads\n\* `clickup` - Clickup\n\* `customerio-app` - Customerio App\n\* `customerio-track` - Customerio Track\n\* `customerio-webhook` - Customerio Webhook\n\* `databricks` - Databricks\n\* `email` - Email\n\* `firebase` - Firebase\n\* `github` - Github\n\* `gitlab` - Gitlab\n\* `google-ads` - Google Ads\n\* `google-analytics` - Google Analytics\n\* `google-cloud-service-account` - Google Cloud Service Account\n\* `google-cloud-storage` - Google Cloud Storage\n\* `google-pubsub` - Google Pubsub\n\* `google-search-console` - Google Search Console\n\* `google-sheets` - Google Sheets\n\* `hubspot` - Hubspot\n\* `intercom` - Intercom\n\* `jira` - Jira\n\* `linear` - Linear\n\* `linkedin-ads` - Linkedin Ads\n\* `meta-ads` - Meta Ads\n\* `pinterest-ads` - Pinterest Ads\n\* `postgresql` - Postgresql\n\* `reddit-ads` - Reddit Ads\n\* `s3-compatible` - S3 Compatible\n\* `salesforce` - Salesforce\n\* `slack` - Slack\n\* `slack-posthog-code` - Slack Posthog Code\n\* `snapchat` - Snapchat\n\* `snowflake` - Snowflake\n\* `stripe` - Stripe\n\* `tiktok-ads` - Tiktok Ads\n\* `twilio` - Twilio\n\* `vercel` - Vercel'
            ),
        config: zod.unknown().optional(),
    })
    .describe('Standard Integration serializer.')

export const IntegrationsEmailVerifyCreateBody = /* @__PURE__ */ zod
    .object({
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
                'snowflake',
                'stripe',
                'tiktok-ads',
                'twilio',
                'vercel',
            ])
            .describe(
                '\* `anthropic` - Anthropic\n\* `apns` - Apple Push\n\* `aws-s3` - Aws S3\n\* `azure-blob` - Azure Blob\n\* `bing-ads` - Bing Ads\n\* `clickup` - Clickup\n\* `customerio-app` - Customerio App\n\* `customerio-track` - Customerio Track\n\* `customerio-webhook` - Customerio Webhook\n\* `databricks` - Databricks\n\* `email` - Email\n\* `firebase` - Firebase\n\* `github` - Github\n\* `gitlab` - Gitlab\n\* `google-ads` - Google Ads\n\* `google-analytics` - Google Analytics\n\* `google-cloud-service-account` - Google Cloud Service Account\n\* `google-cloud-storage` - Google Cloud Storage\n\* `google-pubsub` - Google Pubsub\n\* `google-search-console` - Google Search Console\n\* `google-sheets` - Google Sheets\n\* `hubspot` - Hubspot\n\* `intercom` - Intercom\n\* `jira` - Jira\n\* `linear` - Linear\n\* `linkedin-ads` - Linkedin Ads\n\* `meta-ads` - Meta Ads\n\* `pinterest-ads` - Pinterest Ads\n\* `postgresql` - Postgresql\n\* `reddit-ads` - Reddit Ads\n\* `s3-compatible` - S3 Compatible\n\* `salesforce` - Salesforce\n\* `slack` - Slack\n\* `slack-posthog-code` - Slack Posthog Code\n\* `snapchat` - Snapchat\n\* `snowflake` - Snowflake\n\* `stripe` - Stripe\n\* `tiktok-ads` - Tiktok Ads\n\* `twilio` - Twilio\n\* `vercel` - Vercel'
            ),
        config: zod.unknown().optional(),
    })
    .describe('Standard Integration serializer.')

/**
 * Unified endpoint for generating Domain Connect apply URLs.
 *
 * Accepts a context ("email" or "proxy") and the relevant resource ID.
 * The backend resolves the domain, template variables, and service ID
 * based on context, then builds the signed apply URL.
 */
export const IntegrationsDomainConnectApplyUrlCreateBody = /* @__PURE__ */ zod
    .object({
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
                'snowflake',
                'stripe',
                'tiktok-ads',
                'twilio',
                'vercel',
            ])
            .describe(
                '\* `anthropic` - Anthropic\n\* `apns` - Apple Push\n\* `aws-s3` - Aws S3\n\* `azure-blob` - Azure Blob\n\* `bing-ads` - Bing Ads\n\* `clickup` - Clickup\n\* `customerio-app` - Customerio App\n\* `customerio-track` - Customerio Track\n\* `customerio-webhook` - Customerio Webhook\n\* `databricks` - Databricks\n\* `email` - Email\n\* `firebase` - Firebase\n\* `github` - Github\n\* `gitlab` - Gitlab\n\* `google-ads` - Google Ads\n\* `google-analytics` - Google Analytics\n\* `google-cloud-service-account` - Google Cloud Service Account\n\* `google-cloud-storage` - Google Cloud Storage\n\* `google-pubsub` - Google Pubsub\n\* `google-search-console` - Google Search Console\n\* `google-sheets` - Google Sheets\n\* `hubspot` - Hubspot\n\* `intercom` - Intercom\n\* `jira` - Jira\n\* `linear` - Linear\n\* `linkedin-ads` - Linkedin Ads\n\* `meta-ads` - Meta Ads\n\* `pinterest-ads` - Pinterest Ads\n\* `postgresql` - Postgresql\n\* `reddit-ads` - Reddit Ads\n\* `s3-compatible` - S3 Compatible\n\* `salesforce` - Salesforce\n\* `slack` - Slack\n\* `slack-posthog-code` - Slack Posthog Code\n\* `snapchat` - Snapchat\n\* `snowflake` - Snowflake\n\* `stripe` - Stripe\n\* `tiktok-ads` - Tiktok Ads\n\* `twilio` - Twilio\n\* `vercel` - Vercel'
            ),
        config: zod.unknown().optional(),
    })
    .describe('Standard Integration serializer.')

/**
 * Reuse a GitHub installation already linked to a sibling team in the same organization.
 */
export const IntegrationsGithubLinkExistingCreateBody = /* @__PURE__ */ zod.object({
    source_team_id: zod
        .number()
        .nullish()
        .describe('Sibling team in the same organization whose GitHub installation should be reused.'),
    installation_id: zod
        .string()
        .optional()
        .describe('GitHub installation ID to link; resolved within the organization when source_team_id is omitted.'),
})

/**
 * Mint a User OAuth URL to bootstrap a fresh `code` when the install flow returns without one.
 */
export const IntegrationsGithubOauthAuthorizeCreateBody = /* @__PURE__ */ zod.object({
    installation_id: zod.string().optional().describe('GitHub installation ID to carry through the User OAuth flow.'),
    next: zod.string().optional().describe('Relative URL to redirect to after the OAuth flow completes.'),
    connect_from: zod
        .enum(['posthog_code'])
        .describe('\* `posthog_code` - posthog_code')
        .optional()
        .describe(
            "Originating surface for the connect flow; only 'posthog_code' is recognized.\n\n\* `posthog_code` - posthog_code"
        ),
})

/**
 * Seed GitHub setup callback state without redirecting to GitHub.
 *
 * Used when the user opens an existing installation's settings on github.com (e.g. PostHog
 * Code "Update in GitHub") so the subsequent Setup URL redirect can be validated.
 */
export const IntegrationsGithubPrepareCallbackCreateBody = /* @__PURE__ */ zod.object({
    next: zod
        .string()
        .optional()
        .describe(
            'Relative URL to redirect to after GitHub setup completes (e.g. account-connected for PostHog Code).'
        ),
    installation_id: zod
        .string()
        .optional()
        .describe(
            "GitHub installation ID being managed; binds the seeded update state so a callback can't swap in a different installation."
        ),
})

/**
 * Notify project admins that a member is requesting an integration be connected.
 */
export const integrationsRequestAccessCreateBodyReasonMax = 2000

export const IntegrationsRequestAccessCreateBody = /* @__PURE__ */ zod.object({
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
            'snowflake',
            'stripe',
            'tiktok-ads',
            'twilio',
            'vercel',
        ])
        .describe(
            '\* `anthropic` - Anthropic\n\* `apns` - Apple Push\n\* `aws-s3` - Aws S3\n\* `azure-blob` - Azure Blob\n\* `bing-ads` - Bing Ads\n\* `clickup` - Clickup\n\* `customerio-app` - Customerio App\n\* `customerio-track` - Customerio Track\n\* `customerio-webhook` - Customerio Webhook\n\* `databricks` - Databricks\n\* `email` - Email\n\* `firebase` - Firebase\n\* `github` - Github\n\* `gitlab` - Gitlab\n\* `google-ads` - Google Ads\n\* `google-analytics` - Google Analytics\n\* `google-cloud-service-account` - Google Cloud Service Account\n\* `google-cloud-storage` - Google Cloud Storage\n\* `google-pubsub` - Google Pubsub\n\* `google-search-console` - Google Search Console\n\* `google-sheets` - Google Sheets\n\* `hubspot` - Hubspot\n\* `intercom` - Intercom\n\* `jira` - Jira\n\* `linear` - Linear\n\* `linkedin-ads` - Linkedin Ads\n\* `meta-ads` - Meta Ads\n\* `pinterest-ads` - Pinterest Ads\n\* `postgresql` - Postgresql\n\* `reddit-ads` - Reddit Ads\n\* `s3-compatible` - S3 Compatible\n\* `salesforce` - Salesforce\n\* `slack` - Slack\n\* `slack-posthog-code` - Slack Posthog Code\n\* `snapchat` - Snapchat\n\* `snowflake` - Snowflake\n\* `stripe` - Stripe\n\* `tiktok-ads` - Tiktok Ads\n\* `twilio` - Twilio\n\* `vercel` - Vercel'
        )
        .describe(
            "The kind of integration the member is requesting be connected (e.g. 'slack', 'github').\n\n\* `anthropic` - Anthropic\n\* `apns` - Apple Push\n\* `aws-s3` - Aws S3\n\* `azure-blob` - Azure Blob\n\* `bing-ads` - Bing Ads\n\* `clickup` - Clickup\n\* `customerio-app` - Customerio App\n\* `customerio-track` - Customerio Track\n\* `customerio-webhook` - Customerio Webhook\n\* `databricks` - Databricks\n\* `email` - Email\n\* `firebase` - Firebase\n\* `github` - Github\n\* `gitlab` - Gitlab\n\* `google-ads` - Google Ads\n\* `google-analytics` - Google Analytics\n\* `google-cloud-service-account` - Google Cloud Service Account\n\* `google-cloud-storage` - Google Cloud Storage\n\* `google-pubsub` - Google Pubsub\n\* `google-search-console` - Google Search Console\n\* `google-sheets` - Google Sheets\n\* `hubspot` - Hubspot\n\* `intercom` - Intercom\n\* `jira` - Jira\n\* `linear` - Linear\n\* `linkedin-ads` - Linkedin Ads\n\* `meta-ads` - Meta Ads\n\* `pinterest-ads` - Pinterest Ads\n\* `postgresql` - Postgresql\n\* `reddit-ads` - Reddit Ads\n\* `s3-compatible` - S3 Compatible\n\* `salesforce` - Salesforce\n\* `slack` - Slack\n\* `slack-posthog-code` - Slack Posthog Code\n\* `snapchat` - Snapchat\n\* `snowflake` - Snowflake\n\* `stripe` - Stripe\n\* `tiktok-ads` - Tiktok Ads\n\* `twilio` - Twilio\n\* `vercel` - Vercel"
        ),
    reason: zod
        .string()
        .max(integrationsRequestAccessCreateBodyReasonMax)
        .describe(
            'Explanation from the requester of why this integration is needed. Shown to admins in the notification email.'
        ),
})
