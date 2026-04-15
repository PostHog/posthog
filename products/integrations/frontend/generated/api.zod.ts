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

Provides read-only access to integrations that are scoped to the entire organization
(vs. project-level integrations). Examples include Vercel, AWS Marketplace, etc.

This is read-only. Creation is handled by the integration installation flows
(e.g., Vercel marketplace installation). Deletion requires contacting support
due to billing implications.
 */
export const integrationsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const integrationsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const integrationsListResponseResultsItemCreatedByOneLastNameMax = 150

export const integrationsListResponseResultsItemCreatedByOneEmailMax = 254

export const IntegrationsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                kind: zod.enum(['vercel']).describe('* `vercel` - Vercel'),
                integration_id: zod.string().nullable(),
                config: zod.unknown(),
                created_at: zod.iso.datetime({}),
                updated_at: zod.iso.datetime({}),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(integrationsListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(integrationsListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod.string().max(integrationsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                    email: zod.email().max(integrationsListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                }),
            })
            .describe('Serializer for organization-level integrations.')
    ),
})

/**
 * ViewSet for organization-level integrations.

Provides read-only access to integrations that are scoped to the entire organization
(vs. project-level integrations). Examples include Vercel, AWS Marketplace, etc.

This is read-only. Creation is handled by the integration installation flows
(e.g., Vercel marketplace installation). Deletion requires contacting support
due to billing implications.
 */
export const integrationsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const integrationsRetrieveResponseCreatedByOneFirstNameMax = 150

export const integrationsRetrieveResponseCreatedByOneLastNameMax = 150

export const integrationsRetrieveResponseCreatedByOneEmailMax = 254

export const IntegrationsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        kind: zod.enum(['vercel']).describe('* `vercel` - Vercel'),
        integration_id: zod.string().nullable(),
        config: zod.unknown(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(integrationsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(integrationsRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(integrationsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(integrationsRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
    })
    .describe('Serializer for organization-level integrations.')

/**
 * ViewSet for organization-level integrations.

Provides read-only access to integrations that are scoped to the entire organization
(vs. project-level integrations). Examples include Vercel, AWS Marketplace, etc.

This is read-only. Creation is handled by the integration installation flows
(e.g., Vercel marketplace installation). Deletion requires contacting support
due to billing implications.
 */
export const IntegrationsEnvironmentMappingPartialUpdateBody = /* @__PURE__ */ zod
    .object({})
    .describe('Serializer for organization-level integrations.')

export const integrationsEnvironmentMappingPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const integrationsEnvironmentMappingPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const integrationsEnvironmentMappingPartialUpdateResponseCreatedByOneLastNameMax = 150

export const integrationsEnvironmentMappingPartialUpdateResponseCreatedByOneEmailMax = 254

export const IntegrationsEnvironmentMappingPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        kind: zod.enum(['vercel']).describe('* `vercel` - Vercel'),
        integration_id: zod.string().nullable(),
        config: zod.unknown(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(integrationsEnvironmentMappingPartialUpdateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(integrationsEnvironmentMappingPartialUpdateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(integrationsEnvironmentMappingPartialUpdateResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.email().max(integrationsEnvironmentMappingPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
    })
    .describe('Serializer for organization-level integrations.')

export const integrationsList2ResponseResultsItemCreatedByOneDistinctIdMax = 200

export const integrationsList2ResponseResultsItemCreatedByOneFirstNameMax = 150

export const integrationsList2ResponseResultsItemCreatedByOneLastNameMax = 150

export const integrationsList2ResponseResultsItemCreatedByOneEmailMax = 254

export const IntegrationsList2Response = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.number(),
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
                created_at: zod.iso.datetime({}),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(integrationsList2ResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(integrationsList2ResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod.string().max(integrationsList2ResponseResultsItemCreatedByOneLastNameMax).optional(),
                    email: zod.email().max(integrationsList2ResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                }),
                errors: zod.string(),
                display_name: zod.string(),
            })
            .describe('Standard Integration serializer.')
    ),
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

export const integrationsRetrieve2ResponseCreatedByOneDistinctIdMax = 200

export const integrationsRetrieve2ResponseCreatedByOneFirstNameMax = 150

export const integrationsRetrieve2ResponseCreatedByOneLastNameMax = 150

export const integrationsRetrieve2ResponseCreatedByOneEmailMax = 254

export const IntegrationsRetrieve2Response = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
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
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(integrationsRetrieve2ResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(integrationsRetrieve2ResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(integrationsRetrieve2ResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(integrationsRetrieve2ResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        errors: zod.string(),
        display_name: zod.string(),
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

export const integrationsEmailPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const integrationsEmailPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const integrationsEmailPartialUpdateResponseCreatedByOneLastNameMax = 150

export const integrationsEmailPartialUpdateResponseCreatedByOneEmailMax = 254

export const IntegrationsEmailPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
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
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(integrationsEmailPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(integrationsEmailPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(integrationsEmailPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(integrationsEmailPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        errors: zod.string(),
        display_name: zod.string(),
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

export const IntegrationsGithubBranchesRetrieveResponse = /* @__PURE__ */ zod.object({
    branches: zod.array(zod.string()).describe('List of branch names'),
    default_branch: zod.string().nullish().describe('The default branch of the repository'),
    has_more: zod.boolean().describe('Whether more branches exist beyond the returned page'),
})

export const IntegrationsGithubReposRetrieveResponse = /* @__PURE__ */ zod.object({
    repositories: zod.array(
        zod.object({
            id: zod.number(),
            name: zod.string(),
            full_name: zod.string(),
        })
    ),
    has_more: zod.boolean().describe('Whether more repositories are available beyond this page.'),
})

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
