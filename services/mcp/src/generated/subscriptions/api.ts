/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const SubscriptionsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SubscriptionsListQueryParams = /* @__PURE__ */ zod.object({
    created_by: zod.string().optional().describe('Filter by creator user UUID.'),
    dashboard: zod.number().optional().describe('Filter by dashboard ID.'),
    insight: zod.number().optional().describe('Filter by insight ID.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    ordering: zod.string().optional().describe('Which field to use when ordering the results.'),
    resource_type: zod
        .enum(['ai_prompt', 'dashboard', 'insight'])
        .optional()
        .describe('Filter by subscription resource: insight, dashboard export, or AI report.'),
    search: zod.string().optional().describe('A search term.'),
    target_type: zod.enum(['email', 'slack']).optional().describe('Filter by delivery channel (email or Slack).'),
})

export const SubscriptionsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const subscriptionsCreateBodyAiWindowStartDaysAgoMax = 365

export const subscriptionsCreateBodyAiWindowEndDaysAgoMin = 0
export const subscriptionsCreateBodyAiWindowEndDaysAgoMax = 365

export const subscriptionsCreateBodyIntervalMax = 2147483647

export const subscriptionsCreateBodyBysetposMin = -2147483648
export const subscriptionsCreateBodyBysetposMax = 2147483647

export const subscriptionsCreateBodyCountMin = -2147483648
export const subscriptionsCreateBodyCountMax = 2147483647

export const subscriptionsCreateBodyTitleMax = 100

export const subscriptionsCreateBodySummaryPromptGuideMax = 500

export const SubscriptionsCreateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod
            .number()
            .nullish()
            .describe('Dashboard ID to subscribe to (mutually exclusive with insight on create).'),
        insight: zod
            .number()
            .nullish()
            .describe('Insight ID to subscribe to (mutually exclusive with dashboard on create).'),
        dashboard_export_insights: zod
            .array(zod.number())
            .optional()
            .describe(
                'List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 6.'
            ),
        prompt: zod
            .string()
            .nullish()
            .describe(
                "Free-text prompt that drives the AI-generated report. Required when resource_type is 'ai_prompt'. Max 4000 characters."
            ),
        ai_window_mode: zod
            .enum(['since_last_sent', 'last_n_days', 'days_ago_range'])
            .describe(
                '* `since_last_sent` - Since last report\n* `last_n_days` - Last N days\n* `days_ago_range` - Between X and Y days ago'
            )
            .optional()
            .describe(
                "Analysis window for AI report subscriptions. 'since_last_sent' (default) analyses everything since the previous successful delivery (gap-free); 'last_n_days' analyses a fixed trailing window of ai_window_start_days_ago days; 'days_ago_range' analyses the explicit range from ai_window_start_days_ago to ai_window_end_days_ago days ago.\n\n* `since_last_sent` - Since last report\n* `last_n_days` - Last N days\n* `days_ago_range` - Between X and Y days ago"
            ),
        ai_window_start_days_ago: zod
            .number()
            .min(1)
            .max(subscriptionsCreateBodyAiWindowStartDaysAgoMax)
            .nullish()
            .describe(
                "Lower bound of the analysis window, in days before the run. Required for 'last_n_days' (the N) and 'days_ago_range'; must be empty for 'since_last_sent'. 1-365."
            ),
        ai_window_end_days_ago: zod
            .number()
            .min(subscriptionsCreateBodyAiWindowEndDaysAgoMin)
            .max(subscriptionsCreateBodyAiWindowEndDaysAgoMax)
            .nullish()
            .describe(
                "Upper bound of the analysis window, in days before the run (0 = now). Required for 'days_ago_range' and must be less than ai_window_start_days_ago; must be empty for other modes. 0-365."
            ),
        target_type: zod
            .enum(['email', 'slack'])
            .describe('* `email` - Email\n* `slack` - Slack')
            .describe('Delivery channel: email or slack.\n\n* `email` - Email\n* `slack` - Slack'),
        target_value: zod
            .string()
            .describe('Recipient(s): comma-separated email addresses for email, or Slack channel name/ID for slack.'),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly')
            .describe(
                'How often to deliver: daily, weekly, monthly, or yearly.\n\n* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'
            ),
        interval: zod
            .number()
            .min(1)
            .max(subscriptionsCreateBodyIntervalMax)
            .describe(
                'Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Required on create; must be 1 or greater.'
            ),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish()
            .describe(
                'Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
            ),
        bysetpos: zod
            .number()
            .min(subscriptionsCreateBodyBysetposMin)
            .max(subscriptionsCreateBodyBysetposMax)
            .nullish()
            .describe('Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).'),
        count: zod
            .number()
            .min(subscriptionsCreateBodyCountMin)
            .max(subscriptionsCreateBodyCountMax)
            .nullish()
            .describe('Total number of deliveries before the subscription stops. Null for unlimited.'),
        start_date: zod.iso.datetime({ offset: true }).describe('When to start delivering (ISO 8601 datetime).'),
        until_date: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('When to stop delivering (ISO 8601 datetime). Null for indefinite.'),
        enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether the subscription is active. Set to false to pause delivery without deleting. Auto-set to false when the delivery integration becomes invalid.'
            ),
        title: zod
            .string()
            .max(subscriptionsCreateBodyTitleMax)
            .nullish()
            .describe('Human-readable name for this subscription.'),
        integration_id: zod
            .number()
            .nullish()
            .describe('ID of a connected Slack integration. Required when target_type is slack.'),
        summary_enabled: zod
            .boolean()
            .optional()
            .describe(
                "Whether to attach an AI-generated summary to each delivery (insight and dashboard subscriptions only). Requires the organization to have approved AI data processing, and is subject to the org's active-summary cap and AI credit budget; otherwise the write is rejected. Not applicable to prompt subscriptions, which are themselves AI-generated."
            ),
        summary_prompt_guide: zod
            .string()
            .max(subscriptionsCreateBodySummaryPromptGuideMax)
            .optional()
            .describe(
                'Optional free-text guidance (max 500 chars) steering the AI summary, e.g. which metrics to emphasize. Only settable when AI summary context is enabled for the organization; clearing it (empty string) is always allowed.'
            ),
    })
    .describe('Standard Subscription serializer.')

export const SubscriptionsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this subscription.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SubscriptionsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this subscription.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const subscriptionsPartialUpdateBodyAiWindowStartDaysAgoMax = 365

export const subscriptionsPartialUpdateBodyAiWindowEndDaysAgoMin = 0
export const subscriptionsPartialUpdateBodyAiWindowEndDaysAgoMax = 365

export const subscriptionsPartialUpdateBodyIntervalMax = 2147483647

export const subscriptionsPartialUpdateBodyBysetposMin = -2147483648
export const subscriptionsPartialUpdateBodyBysetposMax = 2147483647

export const subscriptionsPartialUpdateBodyCountMin = -2147483648
export const subscriptionsPartialUpdateBodyCountMax = 2147483647

export const subscriptionsPartialUpdateBodyTitleMax = 100

export const subscriptionsPartialUpdateBodySummaryPromptGuideMax = 500

export const SubscriptionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod
            .number()
            .nullish()
            .describe('Dashboard ID to subscribe to (mutually exclusive with insight on create).'),
        insight: zod
            .number()
            .nullish()
            .describe('Insight ID to subscribe to (mutually exclusive with dashboard on create).'),
        dashboard_export_insights: zod
            .array(zod.number())
            .optional()
            .describe(
                'List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 6.'
            ),
        prompt: zod
            .string()
            .nullish()
            .describe(
                "Free-text prompt that drives the AI-generated report. Required when resource_type is 'ai_prompt'. Max 4000 characters."
            ),
        ai_window_mode: zod
            .enum(['since_last_sent', 'last_n_days', 'days_ago_range'])
            .describe(
                '* `since_last_sent` - Since last report\n* `last_n_days` - Last N days\n* `days_ago_range` - Between X and Y days ago'
            )
            .optional()
            .describe(
                "Analysis window for AI report subscriptions. 'since_last_sent' (default) analyses everything since the previous successful delivery (gap-free); 'last_n_days' analyses a fixed trailing window of ai_window_start_days_ago days; 'days_ago_range' analyses the explicit range from ai_window_start_days_ago to ai_window_end_days_ago days ago.\n\n* `since_last_sent` - Since last report\n* `last_n_days` - Last N days\n* `days_ago_range` - Between X and Y days ago"
            ),
        ai_window_start_days_ago: zod
            .number()
            .min(1)
            .max(subscriptionsPartialUpdateBodyAiWindowStartDaysAgoMax)
            .nullish()
            .describe(
                "Lower bound of the analysis window, in days before the run. Required for 'last_n_days' (the N) and 'days_ago_range'; must be empty for 'since_last_sent'. 1-365."
            ),
        ai_window_end_days_ago: zod
            .number()
            .min(subscriptionsPartialUpdateBodyAiWindowEndDaysAgoMin)
            .max(subscriptionsPartialUpdateBodyAiWindowEndDaysAgoMax)
            .nullish()
            .describe(
                "Upper bound of the analysis window, in days before the run (0 = now). Required for 'days_ago_range' and must be less than ai_window_start_days_ago; must be empty for other modes. 0-365."
            ),
        target_type: zod
            .enum(['email', 'slack'])
            .describe('* `email` - Email\n* `slack` - Slack')
            .optional()
            .describe('Delivery channel: email or slack.\n\n* `email` - Email\n* `slack` - Slack'),
        target_value: zod
            .string()
            .optional()
            .describe('Recipient(s): comma-separated email addresses for email, or Slack channel name/ID for slack.'),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly')
            .optional()
            .describe(
                'How often to deliver: daily, weekly, monthly, or yearly.\n\n* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'
            ),
        interval: zod
            .number()
            .min(1)
            .max(subscriptionsPartialUpdateBodyIntervalMax)
            .optional()
            .describe(
                'Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Required on create; must be 1 or greater.'
            ),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish()
            .describe(
                'Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
            ),
        bysetpos: zod
            .number()
            .min(subscriptionsPartialUpdateBodyBysetposMin)
            .max(subscriptionsPartialUpdateBodyBysetposMax)
            .nullish()
            .describe('Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).'),
        count: zod
            .number()
            .min(subscriptionsPartialUpdateBodyCountMin)
            .max(subscriptionsPartialUpdateBodyCountMax)
            .nullish()
            .describe('Total number of deliveries before the subscription stops. Null for unlimited.'),
        start_date: zod.iso
            .datetime({ offset: true })
            .optional()
            .describe('When to start delivering (ISO 8601 datetime).'),
        until_date: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('When to stop delivering (ISO 8601 datetime). Null for indefinite.'),
        enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether the subscription is active. Set to false to pause delivery without deleting. Auto-set to false when the delivery integration becomes invalid.'
            ),
        title: zod
            .string()
            .max(subscriptionsPartialUpdateBodyTitleMax)
            .nullish()
            .describe('Human-readable name for this subscription.'),
        integration_id: zod
            .number()
            .nullish()
            .describe('ID of a connected Slack integration. Required when target_type is slack.'),
        summary_enabled: zod
            .boolean()
            .optional()
            .describe(
                "Whether to attach an AI-generated summary to each delivery (insight and dashboard subscriptions only). Requires the organization to have approved AI data processing, and is subject to the org's active-summary cap and AI credit budget; otherwise the write is rejected. Not applicable to prompt subscriptions, which are themselves AI-generated."
            ),
        summary_prompt_guide: zod
            .string()
            .max(subscriptionsPartialUpdateBodySummaryPromptGuideMax)
            .optional()
            .describe(
                'Optional free-text guidance (max 500 chars) steering the AI summary, e.g. which metrics to emphasize. Only settable when AI summary context is enabled for the organization; clearing it (empty string) is always allowed.'
            ),
    })
    .describe('Standard Subscription serializer.')

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const SubscriptionsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this subscription.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SubscriptionsTestDeliveryCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this subscription.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Paginated delivery history for a subscription. Requires premium subscriptions.
 * @summary List subscription deliveries
 */
export const SubscriptionsDeliveriesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    subscription_id: zod.number(),
})

export const SubscriptionsDeliveriesListQueryParams = /* @__PURE__ */ zod.object({
    cursor: zod.string().optional().describe('The pagination cursor value.'),
    status: zod
        .enum(['completed', 'failed', 'skipped', 'starting'])
        .optional()
        .describe('Return only deliveries in this run status (starting, completed, failed, or skipped).'),
})

/**
 * Fetch one delivery row by id.
 * @summary Retrieve subscription delivery
 */
export const SubscriptionsDeliveriesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this subscription delivery.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    subscription_id: zod.number(),
})
