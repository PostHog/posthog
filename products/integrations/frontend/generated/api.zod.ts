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
                'apns',
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
                'google-cloud-service-account',
                'google-cloud-storage',
                'google-pubsub',
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
                'salesforce',
                'slack',
                'slack-posthog-code',
                'snapchat',
                'stripe',
                'tiktok-ads',
                'twilio',
                'vercel',
            ])
            .describe(
                '* `apns` - Apple Push\n* `azure-blob` - Azure Blob\n* `bing-ads` - Bing Ads\n* `clickup` - Clickup\n* `customerio-app` - Customerio App\n* `customerio-track` - Customerio Track\n* `customerio-webhook` - Customerio Webhook\n* `databricks` - Databricks\n* `email` - Email\n* `firebase` - Firebase\n* `github` - Github\n* `gitlab` - Gitlab\n* `google-ads` - Google Ads\n* `google-cloud-service-account` - Google Cloud Service Account\n* `google-cloud-storage` - Google Cloud Storage\n* `google-pubsub` - Google Pubsub\n* `google-sheets` - Google Sheets\n* `hubspot` - Hubspot\n* `intercom` - Intercom\n* `jira` - Jira\n* `linear` - Linear\n* `linkedin-ads` - Linkedin Ads\n* `meta-ads` - Meta Ads\n* `pinterest-ads` - Pinterest Ads\n* `postgresql` - Postgresql\n* `reddit-ads` - Reddit Ads\n* `salesforce` - Salesforce\n* `slack` - Slack\n* `slack-posthog-code` - Slack Posthog Code\n* `snapchat` - Snapchat\n* `stripe` - Stripe\n* `tiktok-ads` - Tiktok Ads\n* `twilio` - Twilio\n* `vercel` - Vercel'
            ),
        config: zod.unknown().optional(),
    })
    .describe('Standard Integration serializer.')

export const IntegrationsEmailPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        kind: zod
            .enum([
                'apns',
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
                'google-cloud-service-account',
                'google-cloud-storage',
                'google-pubsub',
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
                '* `apns` - Apple Push\n* `azure-blob` - Azure Blob\n* `bing-ads` - Bing Ads\n* `clickup` - Clickup\n* `customerio-app` - Customerio App\n* `customerio-track` - Customerio Track\n* `customerio-webhook` - Customerio Webhook\n* `databricks` - Databricks\n* `email` - Email\n* `firebase` - Firebase\n* `github` - Github\n* `gitlab` - Gitlab\n* `google-ads` - Google Ads\n* `google-cloud-service-account` - Google Cloud Service Account\n* `google-cloud-storage` - Google Cloud Storage\n* `google-pubsub` - Google Pubsub\n* `google-sheets` - Google Sheets\n* `hubspot` - Hubspot\n* `intercom` - Intercom\n* `jira` - Jira\n* `linear` - Linear\n* `linkedin-ads` - Linkedin Ads\n* `meta-ads` - Meta Ads\n* `pinterest-ads` - Pinterest Ads\n* `postgresql` - Postgresql\n* `reddit-ads` - Reddit Ads\n* `salesforce` - Salesforce\n* `slack` - Slack\n* `slack-posthog-code` - Slack Posthog Code\n* `snapchat` - Snapchat\n* `stripe` - Stripe\n* `tiktok-ads` - Tiktok Ads\n* `twilio` - Twilio\n* `vercel` - Vercel'
            ),
        config: zod.unknown().optional(),
    })
    .describe('Standard Integration serializer.')

export const IntegrationsEmailVerifyCreateBody = /* @__PURE__ */ zod
    .object({
        kind: zod
            .enum([
                'apns',
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
                'google-cloud-service-account',
                'google-cloud-storage',
                'google-pubsub',
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
                'salesforce',
                'slack',
                'slack-posthog-code',
                'snapchat',
                'stripe',
                'tiktok-ads',
                'twilio',
                'vercel',
            ])
            .describe(
                '* `apns` - Apple Push\n* `azure-blob` - Azure Blob\n* `bing-ads` - Bing Ads\n* `clickup` - Clickup\n* `customerio-app` - Customerio App\n* `customerio-track` - Customerio Track\n* `customerio-webhook` - Customerio Webhook\n* `databricks` - Databricks\n* `email` - Email\n* `firebase` - Firebase\n* `github` - Github\n* `gitlab` - Gitlab\n* `google-ads` - Google Ads\n* `google-cloud-service-account` - Google Cloud Service Account\n* `google-cloud-storage` - Google Cloud Storage\n* `google-pubsub` - Google Pubsub\n* `google-sheets` - Google Sheets\n* `hubspot` - Hubspot\n* `intercom` - Intercom\n* `jira` - Jira\n* `linear` - Linear\n* `linkedin-ads` - Linkedin Ads\n* `meta-ads` - Meta Ads\n* `pinterest-ads` - Pinterest Ads\n* `postgresql` - Postgresql\n* `reddit-ads` - Reddit Ads\n* `salesforce` - Salesforce\n* `slack` - Slack\n* `slack-posthog-code` - Slack Posthog Code\n* `snapchat` - Snapchat\n* `stripe` - Stripe\n* `tiktok-ads` - Tiktok Ads\n* `twilio` - Twilio\n* `vercel` - Vercel'
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
                'apns',
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
                'google-cloud-service-account',
                'google-cloud-storage',
                'google-pubsub',
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
                'salesforce',
                'slack',
                'slack-posthog-code',
                'snapchat',
                'stripe',
                'tiktok-ads',
                'twilio',
                'vercel',
            ])
            .describe(
                '* `apns` - Apple Push\n* `azure-blob` - Azure Blob\n* `bing-ads` - Bing Ads\n* `clickup` - Clickup\n* `customerio-app` - Customerio App\n* `customerio-track` - Customerio Track\n* `customerio-webhook` - Customerio Webhook\n* `databricks` - Databricks\n* `email` - Email\n* `firebase` - Firebase\n* `github` - Github\n* `gitlab` - Gitlab\n* `google-ads` - Google Ads\n* `google-cloud-service-account` - Google Cloud Service Account\n* `google-cloud-storage` - Google Cloud Storage\n* `google-pubsub` - Google Pubsub\n* `google-sheets` - Google Sheets\n* `hubspot` - Hubspot\n* `intercom` - Intercom\n* `jira` - Jira\n* `linear` - Linear\n* `linkedin-ads` - Linkedin Ads\n* `meta-ads` - Meta Ads\n* `pinterest-ads` - Pinterest Ads\n* `postgresql` - Postgresql\n* `reddit-ads` - Reddit Ads\n* `salesforce` - Salesforce\n* `slack` - Slack\n* `slack-posthog-code` - Slack Posthog Code\n* `snapchat` - Snapchat\n* `stripe` - Stripe\n* `tiktok-ads` - Tiktok Ads\n* `twilio` - Twilio\n* `vercel` - Vercel'
            ),
        config: zod.unknown().optional(),
    })
    .describe('Standard Integration serializer.')

/**
 * Start GitHub linking: either full App install or OAuth-only (user-to-server).

``**_kwargs`` absorbs ``parent_lookup_uuid`` from the nested
``/api/users/{uuid}/integrations/`` router (same pattern as ``local_evaluation``
under projects).

Usually returns ``install_url`` pointing at ``/installations/new`` so the
user can pick any GitHub org (new or already connected).  GitHub's install
page handles both cases: orgs where the app is installed show "Configure"
(no admin needed), orgs where it isn't show "Install" (needs admin).

**PostHog Code fast path:** when ``connect_from`` is ``"posthog_code"``,
the current project already has a team-level GitHub installation, and the
user has no ``UserIntegration`` for that installation yet, we skip the org
picker and redirect straight to ``/login/oauth/authorize`` so the user
only authorizes themselves and returns to PostHog Code immediately.

In both cases the response key is ``install_url`` for compatibility with callers.
 * @summary Start GitHub personal integration linking
 */
export const UsersIntegrationsGithubStartCreateBody = /* @__PURE__ */ zod.object({
    team_id: zod
        .number()
        .nullish()
        .describe("Optional team/project id (e.g. PostHog Code); web UI uses the session's current team."),
    connect_from: zod
        .string()
        .optional()
        .describe('Optional client hint (e.g. posthog_code) for return routing after OAuth.'),
})
