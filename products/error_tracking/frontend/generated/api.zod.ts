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

export const ErrorTrackingExternalReferencesPartialUpdateBody = /* @__PURE__ */ zod.object({
    integration_id: zod.number().optional(),
    config: zod.unknown().optional(),
    issue: zod.uuid().optional(),
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

export const ErrorTrackingReleasesCreateBody = /* @__PURE__ */ zod.object({
    hash_id: zod.string(),
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

export const ErrorTrackingReleasesPartialUpdateBody = /* @__PURE__ */ zod.object({
    hash_id: zod.string().optional(),
    metadata: zod.unknown().nullish(),
    version: zod.string().optional(),
    project: zod.string().optional(),
})

export const ErrorTrackingStackFramesBatchGetCreateBody = /* @__PURE__ */ zod.object({
    contents: zod.unknown(),
    resolved: zod.boolean(),
    context: zod.unknown().nullish(),
    symbol_set_ref: zod.string().optional(),
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

export const ErrorTrackingSymbolSetsCreateBody = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsUpdateBody = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsPartialUpdateBody = /* @__PURE__ */ zod.object({
    ref: zod.string().optional(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
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

export const ErrorTrackingReleasesCreate2Body = /* @__PURE__ */ zod.object({
    hash_id: zod.string(),
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

export const ErrorTrackingReleasesPartialUpdate2Body = /* @__PURE__ */ zod.object({
    hash_id: zod.string().optional(),
    metadata: zod.unknown().nullish(),
    version: zod.string().optional(),
    project: zod.string().optional(),
})

export const ErrorTrackingSymbolSetsCreate2Body = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsUpdate2Body = /* @__PURE__ */ zod.object({
    ref: zod.string(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsPartialUpdate2Body = /* @__PURE__ */ zod.object({
    ref: zod.string().optional(),
    last_used: zod.iso.datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
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
