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

export const errorTrackingAssignmentRulesListResponseResultsItemOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesListResponseResultsItemOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            filters: zod.unknown(),
            assignee: zod
                .object({
                    type: zod.enum(['user', 'role']).optional(),
                    id: zod.union([zod.number(), zod.uuid()]).optional(),
                })
                .nullable(),
            order_key: zod
                .number()
                .min(errorTrackingAssignmentRulesListResponseResultsItemOrderKeyMin)
                .max(errorTrackingAssignmentRulesListResponseResultsItemOrderKeyMax),
            disabled_data: zod.unknown().nullish(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
        })
    ),
})

export const errorTrackingAssignmentRulesCreateBodyOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesCreateBodyOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesCreateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesCreateBodyOrderKeyMin)
        .max(errorTrackingAssignmentRulesCreateBodyOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const errorTrackingAssignmentRulesRetrieveResponseOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesRetrieveResponseOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    filters: zod.unknown(),
    assignee: zod
        .object({
            type: zod.enum(['user', 'role']).optional(),
            id: zod.union([zod.number(), zod.uuid()]).optional(),
        })
        .nullable(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesRetrieveResponseOrderKeyMin)
        .max(errorTrackingAssignmentRulesRetrieveResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const errorTrackingAssignmentRulesUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesUpdateBodyOrderKeyMin)
        .max(errorTrackingAssignmentRulesUpdateBodyOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const errorTrackingAssignmentRulesUpdateResponseOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesUpdateResponseOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    filters: zod.unknown(),
    assignee: zod
        .object({
            type: zod.enum(['user', 'role']).optional(),
            id: zod.union([zod.number(), zod.uuid()]).optional(),
        })
        .nullable(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesUpdateResponseOrderKeyMin)
        .max(errorTrackingAssignmentRulesUpdateResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const errorTrackingAssignmentRulesPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingAssignmentRulesPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
})

export const errorTrackingAssignmentRulesPartialUpdateResponseOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesPartialUpdateResponseOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    filters: zod.unknown(),
    assignee: zod
        .object({
            type: zod.enum(['user', 'role']).optional(),
            id: zod.union([zod.number(), zod.uuid()]).optional(),
        })
        .nullable(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesPartialUpdateResponseOrderKeyMin)
        .max(errorTrackingAssignmentRulesPartialUpdateResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingExternalReferencesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
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
    ),
})

export const ErrorTrackingExternalReferencesCreateBody = /* @__PURE__ */ zod.object({
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

export const ErrorTrackingExternalReferencesRetrieveResponse = /* @__PURE__ */ zod.object({
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

export const ErrorTrackingExternalReferencesUpdateBody = /* @__PURE__ */ zod.object({
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

export const ErrorTrackingExternalReferencesUpdateResponse = /* @__PURE__ */ zod.object({
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

export const ErrorTrackingExternalReferencesPartialUpdateBody = /* @__PURE__ */ zod.object({
    integration_id: zod.number().optional(),
    config: zod.unknown().optional(),
    issue: zod.uuid().optional(),
})

export const ErrorTrackingExternalReferencesPartialUpdateResponse = /* @__PURE__ */ zod.object({
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

export const ErrorTrackingFingerprintsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            fingerprint: zod.string(),
            issue_id: zod.uuid(),
            created_at: zod.iso.datetime({}),
        })
    ),
})

export const ErrorTrackingFingerprintsRetrieveResponse = /* @__PURE__ */ zod.object({
    fingerprint: zod.string(),
    issue_id: zod.uuid(),
    created_at: zod.iso.datetime({}),
})

export const errorTrackingGroupingRulesListResponseResultsItemOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesListResponseResultsItemOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            filters: zod.unknown(),
            assignee: zod
                .object({
                    type: zod.enum(['user', 'role']).optional(),
                    id: zod.union([zod.number(), zod.uuid()]).optional(),
                })
                .nullable(),
            issue: zod.record(zod.string(), zod.string()).nullable().describe('Issue linked to this rule'),
            order_key: zod
                .number()
                .min(errorTrackingGroupingRulesListResponseResultsItemOrderKeyMin)
                .max(errorTrackingGroupingRulesListResponseResultsItemOrderKeyMax),
            disabled_data: zod.unknown().nullish(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
        })
    ),
})

export const errorTrackingGroupingRulesCreateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesCreateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesCreateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesCreateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesCreateBodyOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const errorTrackingGroupingRulesRetrieveResponseOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesRetrieveResponseOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    filters: zod.unknown(),
    assignee: zod
        .object({
            type: zod.enum(['user', 'role']).optional(),
            id: zod.union([zod.number(), zod.uuid()]).optional(),
        })
        .nullable(),
    issue: zod.record(zod.string(), zod.string()).nullable().describe('Issue linked to this rule'),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesRetrieveResponseOrderKeyMin)
        .max(errorTrackingGroupingRulesRetrieveResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const errorTrackingGroupingRulesUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesUpdateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesUpdateBodyOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const errorTrackingGroupingRulesUpdateResponseOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesUpdateResponseOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    filters: zod.unknown(),
    assignee: zod
        .object({
            type: zod.enum(['user', 'role']).optional(),
            id: zod.union([zod.number(), zod.uuid()]).optional(),
        })
        .nullable(),
    issue: zod.record(zod.string(), zod.string()).nullable().describe('Issue linked to this rule'),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesUpdateResponseOrderKeyMin)
        .max(errorTrackingGroupingRulesUpdateResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
})

export const errorTrackingGroupingRulesPartialUpdateResponseOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesPartialUpdateResponseOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    filters: zod.unknown(),
    assignee: zod
        .object({
            type: zod.enum(['user', 'role']).optional(),
            id: zod.union([zod.number(), zod.uuid()]).optional(),
        })
        .nullable(),
    issue: zod.record(zod.string(), zod.string()).nullable().describe('Issue linked to this rule'),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesPartialUpdateResponseOrderKeyMin)
        .max(errorTrackingGroupingRulesPartialUpdateResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingIssuesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            status: zod
                .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
                .optional()
                .describe(
                    '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
                ),
            name: zod.string().nullish(),
            description: zod.string().nullish(),
            first_seen: zod.iso.datetime({}),
            assignee: zod.object({
                id: zod.union([zod.number(), zod.string()]).nullable(),
                type: zod.string(),
            }),
            external_issues: zod.array(
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
            ),
            cohort: zod
                .object({
                    id: zod.number().optional(),
                    name: zod.string().optional(),
                })
                .nullable(),
        })
    ),
})

export const ErrorTrackingIssuesCreateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string()]).nullable(),
        type: zod.string(),
    }),
    external_issues: zod.array(
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
    ),
})

export const ErrorTrackingIssuesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string()]).nullable(),
        type: zod.string(),
    }),
    external_issues: zod.array(
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
    ),
    cohort: zod
        .object({
            id: zod.number().optional(),
            name: zod.string().optional(),
        })
        .nullable(),
})

export const ErrorTrackingIssuesUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string()]).nullable(),
        type: zod.string(),
    }),
    external_issues: zod.array(
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
    ),
})

export const ErrorTrackingIssuesUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string()]).nullable(),
        type: zod.string(),
    }),
    external_issues: zod.array(
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
    ),
    cohort: zod
        .object({
            id: zod.number().optional(),
            name: zod.string().optional(),
        })
        .nullable(),
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
            id: zod.union([zod.number(), zod.string()]).nullable(),
            type: zod.string(),
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

export const ErrorTrackingIssuesPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string()]).nullable(),
        type: zod.string(),
    }),
    external_issues: zod.array(
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
    ),
    cohort: zod
        .object({
            id: zod.number().optional(),
            name: zod.string().optional(),
        })
        .nullable(),
})

export const ErrorTrackingIssuesAssignPartialUpdateBody = /* @__PURE__ */ zod.object({
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
            id: zod.union([zod.number(), zod.string()]).nullable(),
            type: zod.string(),
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

export const ErrorTrackingIssuesCohortUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string()]).nullable(),
        type: zod.string(),
    }),
    external_issues: zod.array(
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
    ),
})

export const ErrorTrackingIssuesMergeCreateBody = /* @__PURE__ */ zod.object({
    ids: zod.array(zod.uuid()).describe('IDs of the issues to merge into the current issue.'),
})

export const ErrorTrackingIssuesMergeCreateResponse = /* @__PURE__ */ zod.object({
    success: zod.boolean().describe('Whether the merge completed successfully.'),
})

export const ErrorTrackingIssuesSplitCreateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string()]).nullable(),
        type: zod.string(),
    }),
    external_issues: zod.array(
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
    ),
})

export const ErrorTrackingIssuesBulkCreateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string()]).nullable(),
        type: zod.string(),
    }),
    external_issues: zod.array(
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
    ),
})

export const ErrorTrackingReleasesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            hash_id: zod.string(),
            team_id: zod.number(),
            created_at: zod.iso.datetime({}),
            metadata: zod.unknown().nullish(),
            version: zod.string(),
            project: zod.string(),
        })
    ),
})

export const ErrorTrackingReleasesCreateBody = /* @__PURE__ */ zod.object({
    hash_id: zod.string(),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    hash_id: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({}),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesUpdateBody = /* @__PURE__ */ zod.object({
    hash_id: zod.string(),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    hash_id: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({}),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesPartialUpdateBody = /* @__PURE__ */ zod.object({
    hash_id: zod.string().optional(),
    metadata: zod.unknown().nullish(),
    version: zod.string().optional(),
    project: zod.string().optional(),
})

export const ErrorTrackingReleasesPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    hash_id: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({}),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingSpikeEventsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            issue: zod.object({
                id: zod.uuid(),
                name: zod.string().nullable(),
                description: zod.string().nullable(),
            }),
            detected_at: zod.iso.datetime({}),
            computed_baseline: zod.number(),
            current_bucket_value: zod.number(),
        })
    ),
})

export const ErrorTrackingStackFramesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            raw_id: zod.string().describe("Raw frame ID in 'hash/part' format"),
            created_at: zod.iso.datetime({}),
            contents: zod.unknown(),
            resolved: zod.boolean(),
            context: zod.unknown().nullish(),
            symbol_set_ref: zod.string().optional(),
            release: zod.object({
                id: zod.uuid(),
                hash_id: zod.string(),
                team_id: zod.number(),
                created_at: zod.iso.datetime({}),
                metadata: zod.unknown().nullish(),
                version: zod.string(),
                project: zod.string(),
            }),
        })
    ),
})

export const ErrorTrackingStackFramesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    raw_id: zod.string().describe("Raw frame ID in 'hash/part' format"),
    created_at: zod.iso.datetime({}),
    contents: zod.unknown(),
    resolved: zod.boolean(),
    context: zod.unknown().nullish(),
    symbol_set_ref: zod.string().optional(),
    release: zod.object({
        id: zod.uuid(),
        hash_id: zod.string(),
        team_id: zod.number(),
        created_at: zod.iso.datetime({}),
        metadata: zod.unknown().nullish(),
        version: zod.string(),
        project: zod.string(),
    }),
})

export const ErrorTrackingStackFramesBatchGetCreateBody = /* @__PURE__ */ zod.object({
    contents: zod.unknown(),
    resolved: zod.boolean(),
    context: zod.unknown().nullish(),
    symbol_set_ref: zod.string().optional(),
})

export const errorTrackingSuppressionRulesListResponseResultsItemOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesListResponseResultsItemOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            filters: zod.unknown(),
            order_key: zod
                .number()
                .min(errorTrackingSuppressionRulesListResponseResultsItemOrderKeyMin)
                .max(errorTrackingSuppressionRulesListResponseResultsItemOrderKeyMax),
            disabled_data: zod.unknown().nullish(),
            sampling_rate: zod.number().optional(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
        })
    ),
})

export const errorTrackingSuppressionRulesCreateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesCreateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesCreateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesCreateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesCreateBodyOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
    sampling_rate: zod.number().optional(),
})

export const errorTrackingSuppressionRulesRetrieveResponseOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesRetrieveResponseOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesRetrieveResponseOrderKeyMin)
        .max(errorTrackingSuppressionRulesRetrieveResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
    sampling_rate: zod.number().optional(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const errorTrackingSuppressionRulesUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesUpdateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesUpdateBodyOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
    sampling_rate: zod.number().optional(),
})

export const errorTrackingSuppressionRulesUpdateResponseOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesUpdateResponseOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesUpdateResponseOrderKeyMin)
        .max(errorTrackingSuppressionRulesUpdateResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
    sampling_rate: zod.number().optional(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
    sampling_rate: zod.number().optional(),
})

export const errorTrackingSuppressionRulesPartialUpdateResponseOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesPartialUpdateResponseOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesPartialUpdateResponseOrderKeyMin)
        .max(errorTrackingSuppressionRulesPartialUpdateResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
    sampling_rate: zod.number().optional(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
    sampling_rate: zod.number().optional(),
})

export const ErrorTrackingSymbolSetsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            ref: zod.string(),
            team_id: zod.number(),
            created_at: zod.iso.datetime({}),
            last_used: zod.iso.datetime({}).nullish(),
            storage_ptr: zod.string().nullish(),
            failure_reason: zod.string().nullish(),
            release: zod
                .record(zod.string(), zod.unknown())
                .nullable()
                .describe('Release associated with this symbol set'),
        })
    ),
})

export const ErrorTrackingSymbolSetsCreateBody = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    ref: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({}),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
    release: zod.record(zod.string(), zod.unknown()).nullable().describe('Release associated with this symbol set'),
})

export const ErrorTrackingSymbolSetsUpdateBody = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    ref: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({}),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
    release: zod.record(zod.string(), zod.unknown()).nullable().describe('Release associated with this symbol set'),
})

export const ErrorTrackingSymbolSetsPartialUpdateBody = /* @__PURE__ */ zod.object({
    ref: zod.string().optional(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    ref: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({}),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
    release: zod.record(zod.string(), zod.unknown()).nullable().describe('Release associated with this symbol set'),
})

export const ErrorTrackingSymbolSetsFinishUploadUpdateBody = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsBulkDeleteCreateBody = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsBulkFinishUploadCreateBody = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsBulkStartUploadCreateBody = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsStartUploadCreateBody = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingReleasesList2Response = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            hash_id: zod.string(),
            team_id: zod.number(),
            created_at: zod.iso.datetime({}),
            metadata: zod.unknown().nullish(),
            version: zod.string(),
            project: zod.string(),
        })
    ),
})

export const ErrorTrackingReleasesCreate2Body = /* @__PURE__ */ zod.object({
    hash_id: zod.string(),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesRetrieve2Response = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    hash_id: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({}),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesUpdate2Body = /* @__PURE__ */ zod.object({
    hash_id: zod.string(),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesUpdate2Response = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    hash_id: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({}),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesPartialUpdate2Body = /* @__PURE__ */ zod.object({
    hash_id: zod.string().optional(),
    metadata: zod.unknown().nullish(),
    version: zod.string().optional(),
    project: zod.string().optional(),
})

export const ErrorTrackingReleasesPartialUpdate2Response = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    hash_id: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({}),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingSymbolSetsList2Response = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            ref: zod.string(),
            team_id: zod.number(),
            created_at: zod.iso.datetime({}),
            last_used: zod.iso.datetime({}).nullish(),
            storage_ptr: zod.string().nullish(),
            failure_reason: zod.string().nullish(),
            release: zod
                .record(zod.string(), zod.unknown())
                .nullable()
                .describe('Release associated with this symbol set'),
        })
    ),
})

export const ErrorTrackingSymbolSetsCreate2Body = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsRetrieve2Response = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    ref: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({}),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
    release: zod.record(zod.string(), zod.unknown()).nullable().describe('Release associated with this symbol set'),
})

export const ErrorTrackingSymbolSetsUpdate2Body = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsUpdate2Response = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    ref: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({}),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
    release: zod.record(zod.string(), zod.unknown()).nullable().describe('Release associated with this symbol set'),
})

export const ErrorTrackingSymbolSetsPartialUpdate2Body = /* @__PURE__ */ zod.object({
    ref: zod.string().optional(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsPartialUpdate2Response = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    ref: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({}),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
    release: zod.record(zod.string(), zod.unknown()).nullable().describe('Release associated with this symbol set'),
})

export const ErrorTrackingSymbolSetsFinishUploadUpdate2Body = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsBulkDeleteCreate2Body = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsBulkFinishUploadCreate2Body = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsBulkStartUploadCreate2Body = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsStartUploadCreate2Body = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})
