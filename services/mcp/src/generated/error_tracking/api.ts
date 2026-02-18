/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 72 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const ErrorTrackingAssignmentRulesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingAssignmentRulesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const errorTrackingAssignmentRulesListResponseResultsItemOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesListResponseResultsItemOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().uuid(),
            filters: zod.unknown(),
            assignee: zod.string(),
            order_key: zod
                .number()
                .min(errorTrackingAssignmentRulesListResponseResultsItemOrderKeyMin)
                .max(errorTrackingAssignmentRulesListResponseResultsItemOrderKeyMax),
            disabled_data: zod.unknown().nullish(),
        })
    ),
})

export const ErrorTrackingAssignmentRulesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingAssignmentRulesCreateBodyOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesCreateBodyOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesCreateBody = zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesCreateBodyOrderKeyMin)
        .max(errorTrackingAssignmentRulesCreateBodyOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingAssignmentRulesRetrieveParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking assignment rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingAssignmentRulesRetrieveResponseOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesRetrieveResponseOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesRetrieveResponse = zod.object({
    id: zod.string().uuid(),
    filters: zod.unknown(),
    assignee: zod.string(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesRetrieveResponseOrderKeyMin)
        .max(errorTrackingAssignmentRulesRetrieveResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingAssignmentRulesUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking assignment rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingAssignmentRulesUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesUpdateBody = zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesUpdateBodyOrderKeyMin)
        .max(errorTrackingAssignmentRulesUpdateBodyOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const errorTrackingAssignmentRulesUpdateResponseOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesUpdateResponseOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesUpdateResponse = zod.object({
    id: zod.string().uuid(),
    filters: zod.unknown(),
    assignee: zod.string(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesUpdateResponseOrderKeyMin)
        .max(errorTrackingAssignmentRulesUpdateResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingAssignmentRulesPartialUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking assignment rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingAssignmentRulesPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesPartialUpdateBody = zod.object({
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

export const ErrorTrackingAssignmentRulesPartialUpdateResponse = zod.object({
    id: zod.string().uuid(),
    filters: zod.unknown(),
    assignee: zod.string(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesPartialUpdateResponseOrderKeyMin)
        .max(errorTrackingAssignmentRulesPartialUpdateResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingAssignmentRulesDestroyParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking assignment rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingAssignmentRulesReorderPartialUpdateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesReorderPartialUpdateBody = zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingAutocaptureControlsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingAutocaptureControlsListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const errorTrackingAutocaptureControlsListResponseResultsItemSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)

export const ErrorTrackingAutocaptureControlsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().uuid(),
            library: zod.enum(['web']).describe('* `web` - Web'),
            match_type: zod.enum(['all', 'any']).optional().describe('* `all` - All\n* `any` - Any'),
            sample_rate: zod
                .string()
                .regex(errorTrackingAutocaptureControlsListResponseResultsItemSampleRateRegExp)
                .optional(),
            linked_feature_flag: zod.unknown().nullish(),
            event_triggers: zod.array(zod.string().nullable()).nullish(),
            url_triggers: zod.array(zod.unknown().nullable()).nullish(),
            url_blocklist: zod.array(zod.unknown().nullable()).nullish(),
        })
    ),
})

export const ErrorTrackingAutocaptureControlsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingAutocaptureControlsCreateBodySampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')

export const ErrorTrackingAutocaptureControlsCreateBody = zod.object({
    match_type: zod.enum(['all', 'any']).optional().describe('* `all` - All\n* `any` - Any'),
    sample_rate: zod.string().regex(errorTrackingAutocaptureControlsCreateBodySampleRateRegExp).optional(),
    linked_feature_flag: zod.unknown().nullish(),
    event_triggers: zod.array(zod.string().nullable()).nullish(),
    url_triggers: zod.array(zod.unknown().nullable()).nullish(),
    url_blocklist: zod.array(zod.unknown().nullable()).nullish(),
})

export const ErrorTrackingAutocaptureControlsRetrieveParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking auto capture controls.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingAutocaptureControlsRetrieveResponseSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)

export const ErrorTrackingAutocaptureControlsRetrieveResponse = zod.object({
    id: zod.string().uuid(),
    library: zod.enum(['web']).describe('* `web` - Web'),
    match_type: zod.enum(['all', 'any']).optional().describe('* `all` - All\n* `any` - Any'),
    sample_rate: zod.string().regex(errorTrackingAutocaptureControlsRetrieveResponseSampleRateRegExp).optional(),
    linked_feature_flag: zod.unknown().nullish(),
    event_triggers: zod.array(zod.string().nullable()).nullish(),
    url_triggers: zod.array(zod.unknown().nullable()).nullish(),
    url_blocklist: zod.array(zod.unknown().nullable()).nullish(),
})

export const ErrorTrackingAutocaptureControlsUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking auto capture controls.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingAutocaptureControlsUpdateBodySampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')

export const ErrorTrackingAutocaptureControlsUpdateBody = zod.object({
    match_type: zod.enum(['all', 'any']).optional().describe('* `all` - All\n* `any` - Any'),
    sample_rate: zod.string().regex(errorTrackingAutocaptureControlsUpdateBodySampleRateRegExp).optional(),
    linked_feature_flag: zod.unknown().nullish(),
    event_triggers: zod.array(zod.string().nullable()).nullish(),
    url_triggers: zod.array(zod.unknown().nullable()).nullish(),
    url_blocklist: zod.array(zod.unknown().nullable()).nullish(),
})

export const errorTrackingAutocaptureControlsUpdateResponseSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')

export const ErrorTrackingAutocaptureControlsUpdateResponse = zod.object({
    id: zod.string().uuid(),
    library: zod.enum(['web']).describe('* `web` - Web'),
    match_type: zod.enum(['all', 'any']).optional().describe('* `all` - All\n* `any` - Any'),
    sample_rate: zod.string().regex(errorTrackingAutocaptureControlsUpdateResponseSampleRateRegExp).optional(),
    linked_feature_flag: zod.unknown().nullish(),
    event_triggers: zod.array(zod.string().nullable()).nullish(),
    url_triggers: zod.array(zod.unknown().nullable()).nullish(),
    url_blocklist: zod.array(zod.unknown().nullable()).nullish(),
})

export const ErrorTrackingAutocaptureControlsPartialUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking auto capture controls.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingAutocaptureControlsPartialUpdateBodySampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)

export const ErrorTrackingAutocaptureControlsPartialUpdateBody = zod.object({
    match_type: zod.enum(['all', 'any']).optional().describe('* `all` - All\n* `any` - Any'),
    sample_rate: zod.string().regex(errorTrackingAutocaptureControlsPartialUpdateBodySampleRateRegExp).optional(),
    linked_feature_flag: zod.unknown().nullish(),
    event_triggers: zod.array(zod.string().nullable()).nullish(),
    url_triggers: zod.array(zod.unknown().nullable()).nullish(),
    url_blocklist: zod.array(zod.unknown().nullable()).nullish(),
})

export const errorTrackingAutocaptureControlsPartialUpdateResponseSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)

export const ErrorTrackingAutocaptureControlsPartialUpdateResponse = zod.object({
    id: zod.string().uuid(),
    library: zod.enum(['web']).describe('* `web` - Web'),
    match_type: zod.enum(['all', 'any']).optional().describe('* `all` - All\n* `any` - Any'),
    sample_rate: zod.string().regex(errorTrackingAutocaptureControlsPartialUpdateResponseSampleRateRegExp).optional(),
    linked_feature_flag: zod.unknown().nullish(),
    event_triggers: zod.array(zod.string().nullable()).nullish(),
    url_triggers: zod.array(zod.unknown().nullable()).nullish(),
    url_blocklist: zod.array(zod.unknown().nullable()).nullish(),
})

export const ErrorTrackingAutocaptureControlsDestroyParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking auto capture controls.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingExternalReferencesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingExternalReferencesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ErrorTrackingExternalReferencesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod
                    .enum([
                        'slack',
                        'salesforce',
                        'hubspot',
                        'google-pubsub',
                        'google-cloud-storage',
                        'google-ads',
                        'google-sheets',
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
                    ])
                    .describe(
                        '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                    ),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.string().uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingExternalReferencesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingExternalReferencesCreateBody = zod.object({
    integration_id: zod.number(),
    config: zod.unknown(),
    issue: zod.string().uuid(),
})

export const ErrorTrackingExternalReferencesRetrieveParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking external reference.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingExternalReferencesRetrieveResponse = zod.object({
    id: zod.string().uuid(),
    integration: zod.object({
        id: zod.number(),
        kind: zod
            .enum([
                'slack',
                'salesforce',
                'hubspot',
                'google-pubsub',
                'google-cloud-storage',
                'google-ads',
                'google-sheets',
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
            ])
            .describe(
                '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
            ),
        display_name: zod.string(),
    }),
    integration_id: zod.number(),
    config: zod.unknown(),
    issue: zod.string().uuid(),
    external_url: zod.string(),
})

export const ErrorTrackingExternalReferencesUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking external reference.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingExternalReferencesUpdateBody = zod.object({
    integration_id: zod.number(),
    config: zod.unknown(),
    issue: zod.string().uuid(),
})

export const ErrorTrackingExternalReferencesUpdateResponse = zod.object({
    id: zod.string().uuid(),
    integration: zod.object({
        id: zod.number(),
        kind: zod
            .enum([
                'slack',
                'salesforce',
                'hubspot',
                'google-pubsub',
                'google-cloud-storage',
                'google-ads',
                'google-sheets',
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
            ])
            .describe(
                '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
            ),
        display_name: zod.string(),
    }),
    integration_id: zod.number(),
    config: zod.unknown(),
    issue: zod.string().uuid(),
    external_url: zod.string(),
})

export const ErrorTrackingExternalReferencesPartialUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking external reference.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingExternalReferencesPartialUpdateBody = zod.object({
    integration_id: zod.number().optional(),
    config: zod.unknown().optional(),
    issue: zod.string().uuid().optional(),
})

export const ErrorTrackingExternalReferencesPartialUpdateResponse = zod.object({
    id: zod.string().uuid(),
    integration: zod.object({
        id: zod.number(),
        kind: zod
            .enum([
                'slack',
                'salesforce',
                'hubspot',
                'google-pubsub',
                'google-cloud-storage',
                'google-ads',
                'google-sheets',
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
            ])
            .describe(
                '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
            ),
        display_name: zod.string(),
    }),
    integration_id: zod.number(),
    config: zod.unknown(),
    issue: zod.string().uuid(),
    external_url: zod.string(),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const ErrorTrackingExternalReferencesDestroyParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking external reference.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingFingerprintsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingFingerprintsListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ErrorTrackingFingerprintsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            fingerprint: zod.string(),
            issue_id: zod.string().uuid(),
            created_at: zod.string().datetime({}),
        })
    ),
})

export const ErrorTrackingFingerprintsRetrieveParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking issue fingerprint v2.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingFingerprintsRetrieveResponse = zod.object({
    fingerprint: zod.string(),
    issue_id: zod.string().uuid(),
    created_at: zod.string().datetime({}),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const ErrorTrackingFingerprintsDestroyParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking issue fingerprint v2.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingGitProviderFileLinksResolveGithubRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingGitProviderFileLinksResolveGitlabRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingGroupingRulesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingGroupingRulesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const errorTrackingGroupingRulesListResponseResultsItemOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesListResponseResultsItemOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().uuid(),
            filters: zod.unknown(),
            assignee: zod.string(),
            order_key: zod
                .number()
                .min(errorTrackingGroupingRulesListResponseResultsItemOrderKeyMin)
                .max(errorTrackingGroupingRulesListResponseResultsItemOrderKeyMax),
            disabled_data: zod.unknown().nullish(),
        })
    ),
})

export const ErrorTrackingGroupingRulesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingGroupingRulesCreateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesCreateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesCreateBody = zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesCreateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesCreateBodyOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingGroupingRulesRetrieveParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking grouping rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingGroupingRulesRetrieveResponseOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesRetrieveResponseOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesRetrieveResponse = zod.object({
    id: zod.string().uuid(),
    filters: zod.unknown(),
    assignee: zod.string(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesRetrieveResponseOrderKeyMin)
        .max(errorTrackingGroupingRulesRetrieveResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingGroupingRulesUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking grouping rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingGroupingRulesUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesUpdateBody = zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesUpdateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesUpdateBodyOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const errorTrackingGroupingRulesUpdateResponseOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesUpdateResponseOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesUpdateResponse = zod.object({
    id: zod.string().uuid(),
    filters: zod.unknown(),
    assignee: zod.string(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesUpdateResponseOrderKeyMin)
        .max(errorTrackingGroupingRulesUpdateResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingGroupingRulesPartialUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking grouping rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesPartialUpdateBody = zod.object({
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

export const ErrorTrackingGroupingRulesPartialUpdateResponse = zod.object({
    id: zod.string().uuid(),
    filters: zod.unknown(),
    assignee: zod.string(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesPartialUpdateResponseOrderKeyMin)
        .max(errorTrackingGroupingRulesPartialUpdateResponseOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingGroupingRulesDestroyParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking grouping rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingGroupingRulesReorderPartialUpdateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesReorderPartialUpdateBody = zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingIssuesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ErrorTrackingIssuesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().uuid(),
            status: zod
                .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
                .optional()
                .describe(
                    '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
                ),
            name: zod.string().nullish(),
            description: zod.string().nullish(),
            first_seen: zod.string().datetime({}),
            assignee: zod.object({
                id: zod.string(),
                type: zod.string(),
            }),
            external_issues: zod.array(
                zod.object({
                    id: zod.string().uuid(),
                    integration: zod.object({
                        id: zod.number(),
                        kind: zod
                            .enum([
                                'slack',
                                'salesforce',
                                'hubspot',
                                'google-pubsub',
                                'google-cloud-storage',
                                'google-ads',
                                'google-sheets',
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
                            ])
                            .describe(
                                '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                            ),
                        display_name: zod.string(),
                    }),
                    integration_id: zod.number(),
                    config: zod.unknown(),
                    issue: zod.string().uuid(),
                    external_url: zod.string(),
                })
            ),
            cohort: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesCreateBody = zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.string().datetime({}),
    assignee: zod.object({
        id: zod.string(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.string().uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod
                    .enum([
                        'slack',
                        'salesforce',
                        'hubspot',
                        'google-pubsub',
                        'google-cloud-storage',
                        'google-ads',
                        'google-sheets',
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
                    ])
                    .describe(
                        '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                    ),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.string().uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesRetrieveParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesRetrieveResponse = zod.object({
    id: zod.string().uuid(),
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.string().datetime({}),
    assignee: zod.object({
        id: zod.string(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.string().uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod
                    .enum([
                        'slack',
                        'salesforce',
                        'hubspot',
                        'google-pubsub',
                        'google-cloud-storage',
                        'google-ads',
                        'google-sheets',
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
                    ])
                    .describe(
                        '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                    ),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.string().uuid(),
            external_url: zod.string(),
        })
    ),
    cohort: zod.string(),
})

export const ErrorTrackingIssuesUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesUpdateBody = zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.string().datetime({}),
    assignee: zod.object({
        id: zod.string(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.string().uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod
                    .enum([
                        'slack',
                        'salesforce',
                        'hubspot',
                        'google-pubsub',
                        'google-cloud-storage',
                        'google-ads',
                        'google-sheets',
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
                    ])
                    .describe(
                        '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                    ),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.string().uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesUpdateResponse = zod.object({
    id: zod.string().uuid(),
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.string().datetime({}),
    assignee: zod.object({
        id: zod.string(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.string().uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod
                    .enum([
                        'slack',
                        'salesforce',
                        'hubspot',
                        'google-pubsub',
                        'google-cloud-storage',
                        'google-ads',
                        'google-sheets',
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
                    ])
                    .describe(
                        '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                    ),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.string().uuid(),
            external_url: zod.string(),
        })
    ),
    cohort: zod.string(),
})

export const ErrorTrackingIssuesPartialUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesPartialUpdateBody = zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.string().datetime({}).optional(),
    assignee: zod
        .object({
            id: zod.string(),
            type: zod.string(),
        })
        .optional(),
    external_issues: zod
        .array(
            zod.object({
                id: zod.string().uuid(),
                integration: zod.object({
                    id: zod.number(),
                    kind: zod
                        .enum([
                            'slack',
                            'salesforce',
                            'hubspot',
                            'google-pubsub',
                            'google-cloud-storage',
                            'google-ads',
                            'google-sheets',
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
                        ])
                        .describe(
                            '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                        ),
                    display_name: zod.string(),
                }),
                integration_id: zod.number(),
                config: zod.unknown(),
                issue: zod.string().uuid(),
                external_url: zod.string(),
            })
        )
        .optional(),
})

export const ErrorTrackingIssuesPartialUpdateResponse = zod.object({
    id: zod.string().uuid(),
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.string().datetime({}),
    assignee: zod.object({
        id: zod.string(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.string().uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod
                    .enum([
                        'slack',
                        'salesforce',
                        'hubspot',
                        'google-pubsub',
                        'google-cloud-storage',
                        'google-ads',
                        'google-sheets',
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
                    ])
                    .describe(
                        '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                    ),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.string().uuid(),
            external_url: zod.string(),
        })
    ),
    cohort: zod.string(),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const ErrorTrackingIssuesDestroyParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesAssignPartialUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesAssignPartialUpdateBody = zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.string().datetime({}).optional(),
    assignee: zod
        .object({
            id: zod.string(),
            type: zod.string(),
        })
        .optional(),
    external_issues: zod
        .array(
            zod.object({
                id: zod.string().uuid(),
                integration: zod.object({
                    id: zod.number(),
                    kind: zod
                        .enum([
                            'slack',
                            'salesforce',
                            'hubspot',
                            'google-pubsub',
                            'google-cloud-storage',
                            'google-ads',
                            'google-sheets',
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
                        ])
                        .describe(
                            '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                        ),
                    display_name: zod.string(),
                }),
                integration_id: zod.number(),
                config: zod.unknown(),
                issue: zod.string().uuid(),
                external_url: zod.string(),
            })
        )
        .optional(),
})

export const ErrorTrackingIssuesCohortUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesCohortUpdateBody = zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.string().datetime({}),
    assignee: zod.object({
        id: zod.string(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.string().uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod
                    .enum([
                        'slack',
                        'salesforce',
                        'hubspot',
                        'google-pubsub',
                        'google-cloud-storage',
                        'google-ads',
                        'google-sheets',
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
                    ])
                    .describe(
                        '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                    ),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.string().uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesMergeCreateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesMergeCreateBody = zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.string().datetime({}),
    assignee: zod.object({
        id: zod.string(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.string().uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod
                    .enum([
                        'slack',
                        'salesforce',
                        'hubspot',
                        'google-pubsub',
                        'google-cloud-storage',
                        'google-ads',
                        'google-sheets',
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
                    ])
                    .describe(
                        '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                    ),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.string().uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesSplitCreateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesSplitCreateBody = zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.string().datetime({}),
    assignee: zod.object({
        id: zod.string(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.string().uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod
                    .enum([
                        'slack',
                        'salesforce',
                        'hubspot',
                        'google-pubsub',
                        'google-cloud-storage',
                        'google-ads',
                        'google-sheets',
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
                    ])
                    .describe(
                        '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                    ),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.string().uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesActivityRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesBulkCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesBulkCreateBody = zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.string().datetime({}),
    assignee: zod.object({
        id: zod.string(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.string().uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod
                    .enum([
                        'slack',
                        'salesforce',
                        'hubspot',
                        'google-pubsub',
                        'google-cloud-storage',
                        'google-ads',
                        'google-sheets',
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
                    ])
                    .describe(
                        '* `slack` - Slack\n* `salesforce` - Salesforce\n* `hubspot` - Hubspot\n* `google-pubsub` - Google Pubsub\n* `google-cloud-storage` - Google Cloud Storage\n* `google-ads` - Google Ads\n* `google-sheets` - Google Sheets\n* `snapchat` - Snapchat\n* `linkedin-ads` - Linkedin Ads\n* `reddit-ads` - Reddit Ads\n* `tiktok-ads` - Tiktok Ads\n* `bing-ads` - Bing Ads\n* `intercom` - Intercom\n* `email` - Email\n* `linear` - Linear\n* `github` - Github\n* `gitlab` - Gitlab\n* `meta-ads` - Meta Ads\n* `twilio` - Twilio\n* `clickup` - Clickup\n* `vercel` - Vercel\n* `databricks` - Databricks\n* `azure-blob` - Azure Blob\n* `firebase` - Firebase\n* `jira` - Jira'
                    ),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.string().uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesValuesRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingReleasesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingReleasesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ErrorTrackingReleasesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().uuid(),
            hash_id: zod.string(),
            team_id: zod.number(),
            created_at: zod.string().datetime({}),
            metadata: zod.unknown().nullish(),
            version: zod.string(),
            project: zod.string(),
        })
    ),
})

export const ErrorTrackingReleasesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingReleasesCreateBody = zod.object({
    hash_id: zod.string(),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesRetrieveParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking release.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingReleasesRetrieveResponse = zod.object({
    id: zod.string().uuid(),
    hash_id: zod.string(),
    team_id: zod.number(),
    created_at: zod.string().datetime({}),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking release.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingReleasesUpdateBody = zod.object({
    hash_id: zod.string(),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesUpdateResponse = zod.object({
    id: zod.string().uuid(),
    hash_id: zod.string(),
    team_id: zod.number(),
    created_at: zod.string().datetime({}),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesPartialUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking release.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingReleasesPartialUpdateBody = zod.object({
    hash_id: zod.string().optional(),
    metadata: zod.unknown().nullish(),
    version: zod.string().optional(),
    project: zod.string().optional(),
})

export const ErrorTrackingReleasesPartialUpdateResponse = zod.object({
    id: zod.string().uuid(),
    hash_id: zod.string(),
    team_id: zod.number(),
    created_at: zod.string().datetime({}),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesDestroyParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking release.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingReleasesHashRetrieveParams = zod.object({
    hash_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingStackFramesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingStackFramesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ErrorTrackingStackFramesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().uuid(),
            raw_id: zod.string(),
            created_at: zod.string().datetime({}),
            contents: zod.unknown(),
            resolved: zod.boolean(),
            context: zod.unknown().nullish(),
            symbol_set_ref: zod.string().optional(),
            release: zod.object({
                id: zod.string().uuid(),
                hash_id: zod.string(),
                team_id: zod.number(),
                created_at: zod.string().datetime({}),
                metadata: zod.unknown().nullish(),
                version: zod.string(),
                project: zod.string(),
            }),
        })
    ),
})

export const ErrorTrackingStackFramesRetrieveParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking stack frame.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingStackFramesRetrieveResponse = zod.object({
    id: zod.string().uuid(),
    raw_id: zod.string(),
    created_at: zod.string().datetime({}),
    contents: zod.unknown(),
    resolved: zod.boolean(),
    context: zod.unknown().nullish(),
    symbol_set_ref: zod.string().optional(),
    release: zod.object({
        id: zod.string().uuid(),
        hash_id: zod.string(),
        team_id: zod.number(),
        created_at: zod.string().datetime({}),
        metadata: zod.unknown().nullish(),
        version: zod.string(),
        project: zod.string(),
    }),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const ErrorTrackingStackFramesDestroyParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking stack frame.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingStackFramesBatchGetCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingStackFramesBatchGetCreateBody = zod.object({
    contents: zod.unknown(),
    resolved: zod.boolean(),
    context: zod.unknown().nullish(),
    symbol_set_ref: zod.string().optional(),
})

export const ErrorTrackingSuppressionRulesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSuppressionRulesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const errorTrackingSuppressionRulesListResponseResultsItemOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesListResponseResultsItemOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().uuid(),
            filters: zod.unknown(),
            order_key: zod
                .number()
                .min(errorTrackingSuppressionRulesListResponseResultsItemOrderKeyMin)
                .max(errorTrackingSuppressionRulesListResponseResultsItemOrderKeyMax),
        })
    ),
})

export const ErrorTrackingSuppressionRulesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingSuppressionRulesCreateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesCreateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesCreateBody = zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesCreateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesCreateBodyOrderKeyMax),
})

export const ErrorTrackingSuppressionRulesRetrieveParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking suppression rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingSuppressionRulesRetrieveResponseOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesRetrieveResponseOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesRetrieveResponse = zod.object({
    id: zod.string().uuid(),
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesRetrieveResponseOrderKeyMin)
        .max(errorTrackingSuppressionRulesRetrieveResponseOrderKeyMax),
})

export const ErrorTrackingSuppressionRulesUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking suppression rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingSuppressionRulesUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesUpdateBody = zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesUpdateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesUpdateBodyOrderKeyMax),
})

export const errorTrackingSuppressionRulesUpdateResponseOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesUpdateResponseOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesUpdateResponse = zod.object({
    id: zod.string().uuid(),
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesUpdateResponseOrderKeyMin)
        .max(errorTrackingSuppressionRulesUpdateResponseOrderKeyMax),
})

export const ErrorTrackingSuppressionRulesPartialUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking suppression rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesPartialUpdateBody = zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMax)
        .optional(),
})

export const errorTrackingSuppressionRulesPartialUpdateResponseOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesPartialUpdateResponseOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesPartialUpdateResponse = zod.object({
    id: zod.string().uuid(),
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesPartialUpdateResponseOrderKeyMin)
        .max(errorTrackingSuppressionRulesPartialUpdateResponseOrderKeyMax),
})

export const ErrorTrackingSuppressionRulesDestroyParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking suppression rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSuppressionRulesReorderPartialUpdateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesReorderPartialUpdateBody = zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMax)
        .optional(),
})

export const ErrorTrackingSymbolSetsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSymbolSetsListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ErrorTrackingSymbolSetsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().uuid(),
            ref: zod.string(),
            team_id: zod.number(),
            created_at: zod.string().datetime({}),
            last_used: zod.string().datetime({}).nullish(),
            storage_ptr: zod.string().nullish(),
            failure_reason: zod.string().nullish(),
            release: zod.string(),
        })
    ),
})

export const ErrorTrackingSymbolSetsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSymbolSetsCreateBody = zod.object({
    ref: zod.string(),
    last_used: zod.string().datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsRetrieveParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking symbol set.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSymbolSetsRetrieveResponse = zod.object({
    id: zod.string().uuid(),
    ref: zod.string(),
    team_id: zod.number(),
    created_at: zod.string().datetime({}),
    last_used: zod.string().datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
    release: zod.string(),
})

export const ErrorTrackingSymbolSetsUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking symbol set.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSymbolSetsUpdateBody = zod.object({
    ref: zod.string(),
    last_used: zod.string().datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsUpdateResponse = zod.object({
    id: zod.string().uuid(),
    ref: zod.string(),
    team_id: zod.number(),
    created_at: zod.string().datetime({}),
    last_used: zod.string().datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
    release: zod.string(),
})

export const ErrorTrackingSymbolSetsPartialUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking symbol set.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSymbolSetsPartialUpdateBody = zod.object({
    ref: zod.string().optional(),
    last_used: zod.string().datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsPartialUpdateResponse = zod.object({
    id: zod.string().uuid(),
    ref: zod.string(),
    team_id: zod.number(),
    created_at: zod.string().datetime({}),
    last_used: zod.string().datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
    release: zod.string(),
})

export const ErrorTrackingSymbolSetsDestroyParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking symbol set.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSymbolSetsFinishUploadUpdateParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this error tracking symbol set.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSymbolSetsFinishUploadUpdateBody = zod.object({
    ref: zod.string(),
    last_used: zod.string().datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsBulkFinishUploadCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSymbolSetsBulkFinishUploadCreateBody = zod.object({
    ref: zod.string(),
    last_used: zod.string().datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsBulkStartUploadCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSymbolSetsBulkStartUploadCreateBody = zod.object({
    ref: zod.string(),
    last_used: zod.string().datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})

export const ErrorTrackingSymbolSetsStartUploadCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSymbolSetsStartUploadCreateBody = zod.object({
    ref: zod.string(),
    last_used: zod.string().datetime({}).nullish(),
    storage_ptr: zod.string().nullish(),
    failure_reason: zod.string().nullish(),
})
