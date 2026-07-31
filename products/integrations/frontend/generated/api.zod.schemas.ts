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

export const OrganizationIntegrationKindEnumApi = zod.enum(['vercel']).describe('\* `vercel` - Vercel')

export type OrganizationIntegrationKindEnumApi = zod.input<typeof OrganizationIntegrationKindEnumApi>
export type OrganizationIntegrationKindEnumApiOutput = zod.output<typeof OrganizationIntegrationKindEnumApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const PatchedOrganizationIntegrationApi = zod
    .object({
        id: zod.uuid().optional(),
        kind: OrganizationIntegrationKindEnumApi.optional(),
        integration_id: zod.string().nullish(),
        config: zod.unknown().optional(),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        updated_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: UserBasicApi.optional(),
    })
    .describe('Serializer for organization-level integrations.')

export type PatchedOrganizationIntegrationApi = zod.input<typeof PatchedOrganizationIntegrationApi>
export type PatchedOrganizationIntegrationApiOutput = zod.output<typeof PatchedOrganizationIntegrationApi>

export const OrganizationIntegrationApi = zod
    .object({
        id: zod.uuid(),
        kind: OrganizationIntegrationKindEnumApi,
        integration_id: zod.string().nullable(),
        config: zod.unknown(),
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
    })
    .describe('Serializer for organization-level integrations.')

export type OrganizationIntegrationApi = zod.input<typeof OrganizationIntegrationApi>
export type OrganizationIntegrationApiOutput = zod.output<typeof OrganizationIntegrationApi>

export const roleExternalReferenceApiProviderMax = 32

export const roleExternalReferenceApiProviderOrganizationIdMax = 255

export const roleExternalReferenceApiProviderRoleIdMax = 255

export const roleExternalReferenceApiProviderRoleSlugMax = 255

export const roleExternalReferenceApiProviderRoleNameMax = 255

export const RoleExternalReferenceApi = zod.object({
    id: zod.uuid(),
    provider: zod
        .string()
        .max(roleExternalReferenceApiProviderMax)
        .describe('Integration kind (e.g., github, linear, jira, slack).'),
    provider_organization_id: zod
        .string()
        .max(roleExternalReferenceApiProviderOrganizationIdMax)
        .describe('Provider organization\/workspace\/site identifier.'),
    provider_role_id: zod
        .string()
        .max(roleExternalReferenceApiProviderRoleIdMax)
        .describe('Stable provider role identifier.'),
    provider_role_slug: zod
        .string()
        .max(roleExternalReferenceApiProviderRoleSlugMax)
        .nullish()
        .describe('Human-friendly provider role identifier.'),
    provider_role_name: zod
        .string()
        .max(roleExternalReferenceApiProviderRoleNameMax)
        .describe('Display name of the provider role.'),
    role: zod.uuid().describe('PostHog role UUID this external role maps to.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
})

export type RoleExternalReferenceApi = zod.input<typeof RoleExternalReferenceApi>
export type RoleExternalReferenceApiOutput = zod.output<typeof RoleExternalReferenceApi>

export const PaginatedRoleExternalReferenceListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(RoleExternalReferenceApi),
})

export type PaginatedRoleExternalReferenceListApi = zod.input<typeof PaginatedRoleExternalReferenceListApi>
export type PaginatedRoleExternalReferenceListApiOutput = zod.output<typeof PaginatedRoleExternalReferenceListApi>

export const RoleLookupResponseApi = zod.object({
    reference: zod
        .union([RoleExternalReferenceApi, zod.null()])
        .describe('Matching reference, or null if none exists.'),
})

export type RoleLookupResponseApi = zod.input<typeof RoleLookupResponseApi>
export type RoleLookupResponseApiOutput = zod.output<typeof RoleLookupResponseApi>

export const IntegrationKindEnumApi = zod
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
        'pardot',
        'pinterest-ads',
        'postgresql',
        'posthog',
        'reddit-ads',
        'resend',
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
        '\* `anthropic` - Anthropic\n\* `apns` - Apple Push\n\* `aws-s3` - Aws S3\n\* `azure-blob` - Azure Blob\n\* `bing-ads` - Bing Ads\n\* `clickup` - Clickup\n\* `customerio-app` - Customerio App\n\* `customerio-track` - Customerio Track\n\* `customerio-webhook` - Customerio Webhook\n\* `databricks` - Databricks\n\* `email` - Email\n\* `firebase` - Firebase\n\* `github` - Github\n\* `gitlab` - Gitlab\n\* `google-ads` - Google Ads\n\* `google-analytics` - Google Analytics\n\* `google-cloud-service-account` - Google Cloud Service Account\n\* `google-cloud-storage` - Google Cloud Storage\n\* `google-pubsub` - Google Pubsub\n\* `google-search-console` - Google Search Console\n\* `google-sheets` - Google Sheets\n\* `hubspot` - Hubspot\n\* `intercom` - Intercom\n\* `jira` - Jira\n\* `linear` - Linear\n\* `linkedin-ads` - Linkedin Ads\n\* `meta-ads` - Meta Ads\n\* `pardot` - Pardot\n\* `pinterest-ads` - Pinterest Ads\n\* `postgresql` - Postgresql\n\* `posthog` - Posthog\n\* `reddit-ads` - Reddit Ads\n\* `resend` - Resend\n\* `s3-compatible` - S3 Compatible\n\* `salesforce` - Salesforce\n\* `slack` - Slack\n\* `slack-posthog-code` - Slack Posthog Code\n\* `snapchat` - Snapchat\n\* `snowflake` - Snowflake\n\* `stripe` - Stripe\n\* `tiktok-ads` - Tiktok Ads\n\* `twilio` - Twilio\n\* `vercel` - Vercel'
    )

export type IntegrationKindEnumApi = zod.input<typeof IntegrationKindEnumApi>
export type IntegrationKindEnumApiOutput = zod.output<typeof IntegrationKindEnumApi>

export const IntegrationConfigApi = zod
    .object({
        id: zod.number(),
        kind: IntegrationKindEnumApi,
        config: zod.unknown().optional(),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
        errors: zod.string(),
        display_name: zod.string(),
    })
    .describe('Standard Integration serializer.')

export type IntegrationConfigApi = zod.input<typeof IntegrationConfigApi>
export type IntegrationConfigApiOutput = zod.output<typeof IntegrationConfigApi>

export const PaginatedIntegrationConfigListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(IntegrationConfigApi),
})

export type PaginatedIntegrationConfigListApi = zod.input<typeof PaginatedIntegrationConfigListApi>
export type PaginatedIntegrationConfigListApiOutput = zod.output<typeof PaginatedIntegrationConfigListApi>

export const SlackChannelApi = zod.object({
    id: zod.string().describe('Slack channel ID (e.g. C0123ABC) — pass to cdp-functions inputs.channel.'),
    name: zod.string().describe("Slack channel name without the leading '#'."),
    is_private: zod.boolean().describe('True if the channel is private.'),
    is_member: zod.boolean().describe('True if the PostHog Slack app is a member of the channel and can post to it.'),
    is_ext_shared: zod.boolean().describe('True if the channel is shared with another Slack workspace.'),
    is_private_without_access: zod
        .boolean()
        .describe('True if the channel is private and the PostHog Slack app cannot access it.'),
})

export type SlackChannelApi = zod.input<typeof SlackChannelApi>
export type SlackChannelApiOutput = zod.output<typeof SlackChannelApi>

export const SlackChannelsResponseApi = zod.object({
    channels: zod.array(SlackChannelApi).describe('Slack channels visible to the PostHog Slack app.'),
    lastRefreshedAt: zod
        .string()
        .nullish()
        .describe(
            'ISO 8601 timestamp of the last full Slack API refresh (only set on full lists, not single-channel lookups).'
        ),
    has_more: zod.boolean().optional().describe('Whether more channels match the current search beyond this page.'),
})

export type SlackChannelsResponseApi = zod.input<typeof SlackChannelsResponseApi>
export type SlackChannelsResponseApiOutput = zod.output<typeof SlackChannelsResponseApi>

export const PatchedIntegrationConfigApi = zod
    .object({
        id: zod.number().optional(),
        kind: IntegrationKindEnumApi.optional(),
        config: zod.unknown().optional(),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: UserBasicApi.optional(),
        errors: zod.string().optional(),
        display_name: zod.string().optional(),
    })
    .describe('Standard Integration serializer.')

export type PatchedIntegrationConfigApi = zod.input<typeof PatchedIntegrationConfigApi>
export type PatchedIntegrationConfigApiOutput = zod.output<typeof PatchedIntegrationConfigApi>

export const GitHubBranchesResponseApi = zod.object({
    branches: zod.array(zod.string()).describe('List of branch names'),
    default_branch: zod.string().nullish().describe('The default branch of the repository'),
    has_more: zod.boolean().describe('Whether more branches exist beyond the returned page'),
})

export type GitHubBranchesResponseApi = zod.input<typeof GitHubBranchesResponseApi>
export type GitHubBranchesResponseApiOutput = zod.output<typeof GitHubBranchesResponseApi>

export const GitHubRepoApi = zod.object({
    id: zod.number().describe('GitHub repository numeric identifier.'),
    name: zod.string().describe('Repository short name (without the owner prefix).'),
    full_name: zod.string().describe("Fully-qualified repository name as 'owner\/repo'."),
    private: zod.boolean().optional().describe('Whether the repository is private.'),
    default_branch: zod.string().optional().describe("The repository's default branch (e.g. 'main')."),
    language: zod.string().optional().describe('Primary programming language GitHub detected for the repository.'),
    pushed_at: zod
        .string()
        .optional()
        .describe('ISO 8601 timestamp of the most recent push, useful for sorting by recent activity.'),
    archived: zod.boolean().optional().describe('Whether the repository is archived.'),
    can_push: zod
        .boolean()
        .optional()
        .describe('Whether the PostHog GitHub App has write access — required to open pull requests.'),
})

export type GitHubRepoApi = zod.input<typeof GitHubRepoApi>
export type GitHubRepoApiOutput = zod.output<typeof GitHubRepoApi>

export const GitHubReposResponseApi = zod.object({
    repositories: zod.array(GitHubRepoApi),
    has_more: zod.boolean().describe('Whether more repositories are available beyond this page.'),
})

export type GitHubReposResponseApi = zod.input<typeof GitHubReposResponseApi>
export type GitHubReposResponseApiOutput = zod.output<typeof GitHubReposResponseApi>

export const GitHubReposRefreshResponseApi = zod.object({
    repositories: zod.array(GitHubRepoApi).describe('The refreshed repository cache.'),
})

export type GitHubReposRefreshResponseApi = zod.input<typeof GitHubReposRefreshResponseApi>
export type GitHubReposRefreshResponseApiOutput = zod.output<typeof GitHubReposRefreshResponseApi>

export const GitHubTeamApi = zod.object({
    id: zod.number().describe('GitHub team numeric identifier.'),
    slug: zod.string().describe('GitHub team slug.'),
    name: zod.string().describe('GitHub team display name.'),
})

export type GitHubTeamApi = zod.input<typeof GitHubTeamApi>
export type GitHubTeamApiOutput = zod.output<typeof GitHubTeamApi>

export const GitHubTeamsResponseApi = zod.object({
    teams: zod.array(GitHubTeamApi).describe('List of GitHub teams available to the installation organization.'),
    has_more: zod.boolean().describe('Whether more teams are available beyond this page.'),
})

export type GitHubTeamsResponseApi = zod.input<typeof GitHubTeamsResponseApi>
export type GitHubTeamsResponseApiOutput = zod.output<typeof GitHubTeamsResponseApi>

export const JiraProjectApi = zod.object({
    id: zod.string().describe('Jira project ID.'),
    key: zod.string().describe('Jira project key to pass as error tracking config.project_key.'),
    name: zod.string().describe('Jira project display name.'),
})

export type JiraProjectApi = zod.input<typeof JiraProjectApi>
export type JiraProjectApiOutput = zod.output<typeof JiraProjectApi>

export const JiraProjectsResponseApi = zod.object({
    projects: zod.array(JiraProjectApi).describe('Jira projects available to this integration.'),
})

export type JiraProjectsResponseApi = zod.input<typeof JiraProjectsResponseApi>
export type JiraProjectsResponseApiOutput = zod.output<typeof JiraProjectsResponseApi>

export const LinearTeamApi = zod.object({
    id: zod.string().describe('Linear team ID to pass as error tracking config.team_id.'),
    name: zod.string().describe('Linear team display name.'),
})

export type LinearTeamApi = zod.input<typeof LinearTeamApi>
export type LinearTeamApiOutput = zod.output<typeof LinearTeamApi>

export const LinearTeamsResponseApi = zod.object({
    teams: zod.array(LinearTeamApi).describe('Linear teams available to this integration.'),
})

export type LinearTeamsResponseApi = zod.input<typeof LinearTeamsResponseApi>
export type LinearTeamsResponseApiOutput = zod.output<typeof LinearTeamsResponseApi>

export const GitHubAvailableInstallationApi = zod.object({
    installation_id: zod
        .string()
        .describe('GitHub installation ID to pass to github\/link_existing when linking this installation.'),
    account_name: zod
        .string()
        .nullable()
        .describe('GitHub account (organization or user) the installation belongs to, for display in the picker.'),
    account_type: zod.string().nullable().describe("GitHub account type, e.g. 'Organization' or 'User'."),
    source_team_id: zod.number().describe('A project in the organization that already has this installation linked.'),
})

export type GitHubAvailableInstallationApi = zod.input<typeof GitHubAvailableInstallationApi>
export type GitHubAvailableInstallationApiOutput = zod.output<typeof GitHubAvailableInstallationApi>

export const GitHubAvailableInstallationsResponseApi = zod.object({
    installations: zod
        .array(GitHubAvailableInstallationApi)
        .describe('Distinct GitHub installations in the organization available to link to this project.'),
})

export type GitHubAvailableInstallationsResponseApi = zod.input<typeof GitHubAvailableInstallationsResponseApi>
export type GitHubAvailableInstallationsResponseApiOutput = zod.output<typeof GitHubAvailableInstallationsResponseApi>

export const GitHubLinkExistingRequestApi = zod.object({
    source_team_id: zod
        .number()
        .nullish()
        .describe('Sibling team in the same organization whose GitHub installation should be reused.'),
    installation_id: zod
        .string()
        .optional()
        .describe('GitHub installation ID to link; resolved within the organization when source_team_id is omitted.'),
})

export type GitHubLinkExistingRequestApi = zod.input<typeof GitHubLinkExistingRequestApi>
export type GitHubLinkExistingRequestApiOutput = zod.output<typeof GitHubLinkExistingRequestApi>

export const ConnectFromEnumApi = zod.enum(['posthog_code']).describe('\* `posthog_code` - posthog_code')

export type ConnectFromEnumApi = zod.input<typeof ConnectFromEnumApi>
export type ConnectFromEnumApiOutput = zod.output<typeof ConnectFromEnumApi>

export const GitHubOAuthAuthorizeRequestApi = zod.object({
    installation_id: zod.string().optional().describe('GitHub installation ID to carry through the User OAuth flow.'),
    next: zod.string().optional().describe('Relative URL to redirect to after the OAuth flow completes.'),
    connect_from: ConnectFromEnumApi.optional().describe(
        "Originating surface for the connect flow; only 'posthog_code' is recognized.\n\n\* `posthog_code` - posthog_code"
    ),
})

export type GitHubOAuthAuthorizeRequestApi = zod.input<typeof GitHubOAuthAuthorizeRequestApi>
export type GitHubOAuthAuthorizeRequestApiOutput = zod.output<typeof GitHubOAuthAuthorizeRequestApi>

export const GitHubOAuthAuthorizeResponseApi = zod.object({
    oauth_url: zod.string().describe('GitHub User OAuth URL the client should redirect to.'),
})

export type GitHubOAuthAuthorizeResponseApi = zod.input<typeof GitHubOAuthAuthorizeResponseApi>
export type GitHubOAuthAuthorizeResponseApiOutput = zod.output<typeof GitHubOAuthAuthorizeResponseApi>

export const GitHubPrepareCallbackRequestApi = zod.object({
    next: zod
        .string()
        .optional()
        .describe(
            'Relative URL to redirect to after GitHub setup completes (e.g. account-connected for PostHog Desktop).'
        ),
    installation_id: zod
        .string()
        .optional()
        .describe(
            "GitHub installation ID being managed; binds the seeded update state so a callback can't swap in a different installation."
        ),
})

export type GitHubPrepareCallbackRequestApi = zod.input<typeof GitHubPrepareCallbackRequestApi>
export type GitHubPrepareCallbackRequestApiOutput = zod.output<typeof GitHubPrepareCallbackRequestApi>

export const integrationAccessRequestApiReasonMax = 2000

export const IntegrationAccessRequestApi = zod.object({
    kind: IntegrationKindEnumApi.describe(
        "The kind of integration the member is requesting be connected (e.g. 'slack', 'github').\n\n\* `anthropic` - Anthropic\n\* `apns` - Apple Push\n\* `aws-s3` - Aws S3\n\* `azure-blob` - Azure Blob\n\* `bing-ads` - Bing Ads\n\* `clickup` - Clickup\n\* `customerio-app` - Customerio App\n\* `customerio-track` - Customerio Track\n\* `customerio-webhook` - Customerio Webhook\n\* `databricks` - Databricks\n\* `email` - Email\n\* `firebase` - Firebase\n\* `github` - Github\n\* `gitlab` - Gitlab\n\* `google-ads` - Google Ads\n\* `google-analytics` - Google Analytics\n\* `google-cloud-service-account` - Google Cloud Service Account\n\* `google-cloud-storage` - Google Cloud Storage\n\* `google-pubsub` - Google Pubsub\n\* `google-search-console` - Google Search Console\n\* `google-sheets` - Google Sheets\n\* `hubspot` - Hubspot\n\* `intercom` - Intercom\n\* `jira` - Jira\n\* `linear` - Linear\n\* `linkedin-ads` - Linkedin Ads\n\* `meta-ads` - Meta Ads\n\* `pardot` - Pardot\n\* `pinterest-ads` - Pinterest Ads\n\* `postgresql` - Postgresql\n\* `posthog` - Posthog\n\* `reddit-ads` - Reddit Ads\n\* `resend` - Resend\n\* `s3-compatible` - S3 Compatible\n\* `salesforce` - Salesforce\n\* `slack` - Slack\n\* `slack-posthog-code` - Slack Posthog Code\n\* `snapchat` - Snapchat\n\* `snowflake` - Snowflake\n\* `stripe` - Stripe\n\* `tiktok-ads` - Tiktok Ads\n\* `twilio` - Twilio\n\* `vercel` - Vercel"
    ),
    reason: zod
        .string()
        .max(integrationAccessRequestApiReasonMax)
        .describe(
            'Explanation from the requester of why this integration is needed. Shown to admins in the notification email.'
        ),
})

export type IntegrationAccessRequestApi = zod.input<typeof IntegrationAccessRequestApi>
export type IntegrationAccessRequestApiOutput = zod.output<typeof IntegrationAccessRequestApi>

export const IntegrationAccessRequestResponseApi = zod.object({
    success: zod.boolean().describe('Whether the access request was accepted and the project admins were notified.'),
})

export type IntegrationAccessRequestResponseApi = zod.input<typeof IntegrationAccessRequestResponseApi>
export type IntegrationAccessRequestResponseApiOutput = zod.output<typeof IntegrationAccessRequestResponseApi>
