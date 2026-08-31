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

export const subscriptionsCreateBodyAiPromptConfigOneWindowOneModeDefault = `since_last_sent`
export const subscriptionsCreateBodyAiPromptConfigOneWindowOneStartDaysAgoMax = 365

export const subscriptionsCreateBodyAiPromptConfigOneWindowOneEndDaysAgoMin = 0
export const subscriptionsCreateBodyAiPromptConfigOneWindowOneEndDaysAgoMax = 365

export const subscriptionsCreateBodyContextsMax = 3

export const subscriptionsCreateBodyProactiveConfigOneEnabledDefault = false
export const subscriptionsCreateBodyProactiveConfigOneRepositoryMax = 255

export const subscriptionsCreateBodyProactiveConfigOneCreateDraftPrDefault = false
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
                'List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 10.'
            ),
        prompt: zod
            .string()
            .nullish()
            .describe(
                "Free-text prompt that drives the AI-generated report. Required when resource_type is 'ai_prompt'. Max 4000 characters."
            ),
        ai_prompt_config: zod
            .object({
                window: zod
                    .object({
                        mode: zod
                            .enum(['since_last_sent', 'last_n_days', 'days_ago_range'])
                            .describe(
                                '\* `since_last_sent` - Since last report\n\* `last_n_days` - Last N days\n\* `days_ago_range` - Between X and Y days ago'
                            )
                            .default(subscriptionsCreateBodyAiPromptConfigOneWindowOneModeDefault)
                            .describe(
                                "What the report analyzes each run:\n\* `since_last_sent` (default) — everything since the previous successful scheduled delivery (gap-free; test\/manual sends don't move the anchor)\n\* `last_n_days` — a fixed trailing window of start_days_ago days\n\* `days_ago_range` — the explicit range from start_days_ago to end_days_ago days ago\n\n\* `since_last_sent` - Since last report\n\* `last_n_days` - Last N days\n\* `days_ago_range` - Between X and Y days ago"
                            ),
                        start_days_ago: zod
                            .number()
                            .min(1)
                            .max(subscriptionsCreateBodyAiPromptConfigOneWindowOneStartDaysAgoMax)
                            .nullish()
                            .describe(
                                "Lower bound of the analysis window, in days before the run. Required for 'last_n_days' (the N) and 'days_ago_range'; ignored for 'since_last_sent'. 1-365."
                            ),
                        end_days_ago: zod
                            .number()
                            .min(subscriptionsCreateBodyAiPromptConfigOneWindowOneEndDaysAgoMin)
                            .max(subscriptionsCreateBodyAiPromptConfigOneWindowOneEndDaysAgoMax)
                            .nullish()
                            .describe(
                                "Upper bound of the analysis window, in days before the run (0 = now). Required for 'days_ago_range' and must be less than start_days_ago; ignored for other modes. 0-365."
                            ),
                    })
                    .optional()
                    .describe(
                        "Analysis window for the report. Omitted = 'since_last_sent' (everything since the previous scheduled delivery)."
                    ),
            })
            .optional()
            .describe(
                "Configuration for AI report subscriptions (analysis window, future knobs). Only valid when resource_type is 'ai_prompt'. Replaced wholesale on writes."
            ),
        contexts: zod
            .array(
                zod.union([
                    zod.object({
                        dashboard_id: zod.number().min(1),
                    }),
                    zod.object({
                        insight_id: zod.number().min(1),
                    }),
                ])
            )
            .max(subscriptionsCreateBodyContextsMax)
            .optional()
            .describe(
                'Complete dashboard and insight context for an AI report. Omit on PATCH to preserve, pass an empty list to clear, or pass up to 3 items to replace all contexts.'
            ),
        proactive_config: zod
            .object({
                enabled: zod
                    .boolean()
                    .default(subscriptionsCreateBodyProactiveConfigOneEnabledDefault)
                    .describe('Whether future AI report deliveries may run proactive follow-up.'),
                repository: zod
                    .string()
                    .max(subscriptionsCreateBodyProactiveConfigOneRepositoryMax)
                    .nullish()
                    .describe(
                        'Exact repository in owner\/repository format. Required before draft pull requests are allowed.'
                    ),
                repository_integration_id: zod
                    .number()
                    .min(1)
                    .nullish()
                    .describe(
                        'Exact GitHub integration selected with the repository for draft pull request authorization.'
                    ),
                create_draft_pr: zod
                    .boolean()
                    .default(subscriptionsCreateBodyProactiveConfigOneCreateDraftPrDefault)
                    .describe('Whether Pulse may create one draft pull request on a future delivery.'),
                public_research_subject_id: zod
                    .uuid()
                    .nullish()
                    .describe('Optional eligible reviewed public research subject. Omit to disable public research.'),
            })
            .optional()
            .describe('Optional standing consent and limits for proactive follow-up on future AI report deliveries.'),
        target_type: zod
            .enum(['email', 'slack'])
            .describe('\* `email` - Email\n\* `slack` - Slack')
            .describe('Delivery channel: email or slack.\n\n\* `email` - Email\n\* `slack` - Slack'),
        target_value: zod
            .string()
            .describe('Recipient(s): comma-separated email addresses for email, or Slack channel name\/ID for slack.'),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('\* `daily` - Daily\n\* `weekly` - Weekly\n\* `monthly` - Monthly\n\* `yearly` - Yearly')
            .describe(
                'How often to deliver: daily, weekly, monthly, or yearly.\n\n\* `daily` - Daily\n\* `weekly` - Weekly\n\* `monthly` - Monthly\n\* `yearly` - Yearly'
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
                        '\* `monday` - Monday\n\* `tuesday` - Tuesday\n\* `wednesday` - Wednesday\n\* `thursday` - Thursday\n\* `friday` - Friday\n\* `saturday` - Saturday\n\* `sunday` - Sunday'
                    )
            )
            .nullish()
            .describe(
                'Days of week for daily or weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
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
        deleted: zod.boolean().optional().describe('Set to true to soft-delete. Subscriptions cannot be hard-deleted.'),
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
        invite_message: zod
            .string()
            .nullish()
            .describe('Optional message included in the invitation email when adding new recipients.'),
        send_test_now: zod
            .boolean()
            .optional()
            .describe(
                'Whether to immediately deliver the subscription once on save so the editor can confirm it looks right. Defaults to true on create. When omitted on update, a delivery is sent only if the edit changed what gets delivered (recipient, channel, source) or re-enabled the subscription. The recurring schedule is unaffected.'
            ),
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

export const subscriptionsUpdateBodyAiPromptConfigOneWindowOneModeDefault = `since_last_sent`
export const subscriptionsUpdateBodyAiPromptConfigOneWindowOneStartDaysAgoMax = 365

export const subscriptionsUpdateBodyAiPromptConfigOneWindowOneEndDaysAgoMin = 0
export const subscriptionsUpdateBodyAiPromptConfigOneWindowOneEndDaysAgoMax = 365

export const subscriptionsUpdateBodyContextsMax = 3

export const subscriptionsUpdateBodyProactiveConfigOneEnabledDefault = false
export const subscriptionsUpdateBodyProactiveConfigOneRepositoryMax = 255

export const subscriptionsUpdateBodyProactiveConfigOneCreateDraftPrDefault = false
export const subscriptionsUpdateBodyIntervalMax = 2147483647

export const subscriptionsUpdateBodyBysetposMin = -2147483648
export const subscriptionsUpdateBodyBysetposMax = 2147483647

export const subscriptionsUpdateBodyCountMin = -2147483648
export const subscriptionsUpdateBodyCountMax = 2147483647

export const subscriptionsUpdateBodyTitleMax = 100

export const subscriptionsUpdateBodySummaryPromptGuideMax = 500

export const SubscriptionsUpdateBody = /* @__PURE__ */ zod
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
                'List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 10.'
            ),
        prompt: zod
            .string()
            .nullish()
            .describe(
                "Free-text prompt that drives the AI-generated report. Required when resource_type is 'ai_prompt'. Max 4000 characters."
            ),
        ai_prompt_config: zod
            .object({
                window: zod
                    .object({
                        mode: zod
                            .enum(['since_last_sent', 'last_n_days', 'days_ago_range'])
                            .describe(
                                '\* `since_last_sent` - Since last report\n\* `last_n_days` - Last N days\n\* `days_ago_range` - Between X and Y days ago'
                            )
                            .default(subscriptionsUpdateBodyAiPromptConfigOneWindowOneModeDefault)
                            .describe(
                                "What the report analyzes each run:\n\* `since_last_sent` (default) — everything since the previous successful scheduled delivery (gap-free; test\/manual sends don't move the anchor)\n\* `last_n_days` — a fixed trailing window of start_days_ago days\n\* `days_ago_range` — the explicit range from start_days_ago to end_days_ago days ago\n\n\* `since_last_sent` - Since last report\n\* `last_n_days` - Last N days\n\* `days_ago_range` - Between X and Y days ago"
                            ),
                        start_days_ago: zod
                            .number()
                            .min(1)
                            .max(subscriptionsUpdateBodyAiPromptConfigOneWindowOneStartDaysAgoMax)
                            .nullish()
                            .describe(
                                "Lower bound of the analysis window, in days before the run. Required for 'last_n_days' (the N) and 'days_ago_range'; ignored for 'since_last_sent'. 1-365."
                            ),
                        end_days_ago: zod
                            .number()
                            .min(subscriptionsUpdateBodyAiPromptConfigOneWindowOneEndDaysAgoMin)
                            .max(subscriptionsUpdateBodyAiPromptConfigOneWindowOneEndDaysAgoMax)
                            .nullish()
                            .describe(
                                "Upper bound of the analysis window, in days before the run (0 = now). Required for 'days_ago_range' and must be less than start_days_ago; ignored for other modes. 0-365."
                            ),
                    })
                    .optional()
                    .describe(
                        "Analysis window for the report. Omitted = 'since_last_sent' (everything since the previous scheduled delivery)."
                    ),
            })
            .optional()
            .describe(
                "Configuration for AI report subscriptions (analysis window, future knobs). Only valid when resource_type is 'ai_prompt'. Replaced wholesale on writes."
            ),
        contexts: zod
            .array(
                zod.union([
                    zod.object({
                        dashboard_id: zod.number().min(1),
                    }),
                    zod.object({
                        insight_id: zod.number().min(1),
                    }),
                ])
            )
            .max(subscriptionsUpdateBodyContextsMax)
            .optional()
            .describe(
                'Complete dashboard and insight context for an AI report. Omit on PATCH to preserve, pass an empty list to clear, or pass up to 3 items to replace all contexts.'
            ),
        proactive_config: zod
            .object({
                enabled: zod
                    .boolean()
                    .default(subscriptionsUpdateBodyProactiveConfigOneEnabledDefault)
                    .describe('Whether future AI report deliveries may run proactive follow-up.'),
                repository: zod
                    .string()
                    .max(subscriptionsUpdateBodyProactiveConfigOneRepositoryMax)
                    .nullish()
                    .describe(
                        'Exact repository in owner\/repository format. Required before draft pull requests are allowed.'
                    ),
                repository_integration_id: zod
                    .number()
                    .min(1)
                    .nullish()
                    .describe(
                        'Exact GitHub integration selected with the repository for draft pull request authorization.'
                    ),
                create_draft_pr: zod
                    .boolean()
                    .default(subscriptionsUpdateBodyProactiveConfigOneCreateDraftPrDefault)
                    .describe('Whether Pulse may create one draft pull request on a future delivery.'),
                public_research_subject_id: zod
                    .uuid()
                    .nullish()
                    .describe('Optional eligible reviewed public research subject. Omit to disable public research.'),
            })
            .optional()
            .describe('Optional standing consent and limits for proactive follow-up on future AI report deliveries.'),
        target_type: zod
            .enum(['email', 'slack'])
            .describe('\* `email` - Email\n\* `slack` - Slack')
            .describe('Delivery channel: email or slack.\n\n\* `email` - Email\n\* `slack` - Slack'),
        target_value: zod
            .string()
            .describe('Recipient(s): comma-separated email addresses for email, or Slack channel name\/ID for slack.'),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('\* `daily` - Daily\n\* `weekly` - Weekly\n\* `monthly` - Monthly\n\* `yearly` - Yearly')
            .describe(
                'How often to deliver: daily, weekly, monthly, or yearly.\n\n\* `daily` - Daily\n\* `weekly` - Weekly\n\* `monthly` - Monthly\n\* `yearly` - Yearly'
            ),
        interval: zod
            .number()
            .min(1)
            .max(subscriptionsUpdateBodyIntervalMax)
            .describe(
                'Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Required on create; must be 1 or greater.'
            ),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '\* `monday` - Monday\n\* `tuesday` - Tuesday\n\* `wednesday` - Wednesday\n\* `thursday` - Thursday\n\* `friday` - Friday\n\* `saturday` - Saturday\n\* `sunday` - Sunday'
                    )
            )
            .nullish()
            .describe(
                'Days of week for daily or weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
            ),
        bysetpos: zod
            .number()
            .min(subscriptionsUpdateBodyBysetposMin)
            .max(subscriptionsUpdateBodyBysetposMax)
            .nullish()
            .describe('Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).'),
        count: zod
            .number()
            .min(subscriptionsUpdateBodyCountMin)
            .max(subscriptionsUpdateBodyCountMax)
            .nullish()
            .describe('Total number of deliveries before the subscription stops. Null for unlimited.'),
        start_date: zod.iso.datetime({ offset: true }).describe('When to start delivering (ISO 8601 datetime).'),
        until_date: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('When to stop delivering (ISO 8601 datetime). Null for indefinite.'),
        deleted: zod.boolean().optional().describe('Set to true to soft-delete. Subscriptions cannot be hard-deleted.'),
        enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether the subscription is active. Set to false to pause delivery without deleting. Auto-set to false when the delivery integration becomes invalid.'
            ),
        title: zod
            .string()
            .max(subscriptionsUpdateBodyTitleMax)
            .nullish()
            .describe('Human-readable name for this subscription.'),
        integration_id: zod
            .number()
            .nullish()
            .describe('ID of a connected Slack integration. Required when target_type is slack.'),
        invite_message: zod
            .string()
            .nullish()
            .describe('Optional message included in the invitation email when adding new recipients.'),
        send_test_now: zod
            .boolean()
            .optional()
            .describe(
                'Whether to immediately deliver the subscription once on save so the editor can confirm it looks right. Defaults to true on create. When omitted on update, a delivery is sent only if the edit changed what gets delivered (recipient, channel, source) or re-enabled the subscription. The recurring schedule is unaffected.'
            ),
        summary_enabled: zod
            .boolean()
            .optional()
            .describe(
                "Whether to attach an AI-generated summary to each delivery (insight and dashboard subscriptions only). Requires the organization to have approved AI data processing, and is subject to the org's active-summary cap and AI credit budget; otherwise the write is rejected. Not applicable to prompt subscriptions, which are themselves AI-generated."
            ),
        summary_prompt_guide: zod
            .string()
            .max(subscriptionsUpdateBodySummaryPromptGuideMax)
            .optional()
            .describe(
                'Optional free-text guidance (max 500 chars) steering the AI summary, e.g. which metrics to emphasize. Only settable when AI summary context is enabled for the organization; clearing it (empty string) is always allowed.'
            ),
    })
    .describe('Standard Subscription serializer.')

export const subscriptionsPartialUpdateBodyAiPromptConfigOneWindowOneModeDefault = `since_last_sent`
export const subscriptionsPartialUpdateBodyAiPromptConfigOneWindowOneStartDaysAgoMax = 365

export const subscriptionsPartialUpdateBodyAiPromptConfigOneWindowOneEndDaysAgoMin = 0
export const subscriptionsPartialUpdateBodyAiPromptConfigOneWindowOneEndDaysAgoMax = 365

export const subscriptionsPartialUpdateBodyContextsMax = 3

export const subscriptionsPartialUpdateBodyProactiveConfigOneEnabledDefault = false
export const subscriptionsPartialUpdateBodyProactiveConfigOneRepositoryMax = 255

export const subscriptionsPartialUpdateBodyProactiveConfigOneCreateDraftPrDefault = false
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
                'List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 10.'
            ),
        prompt: zod
            .string()
            .nullish()
            .describe(
                "Free-text prompt that drives the AI-generated report. Required when resource_type is 'ai_prompt'. Max 4000 characters."
            ),
        ai_prompt_config: zod
            .object({
                window: zod
                    .object({
                        mode: zod
                            .enum(['since_last_sent', 'last_n_days', 'days_ago_range'])
                            .describe(
                                '\* `since_last_sent` - Since last report\n\* `last_n_days` - Last N days\n\* `days_ago_range` - Between X and Y days ago'
                            )
                            .default(subscriptionsPartialUpdateBodyAiPromptConfigOneWindowOneModeDefault)
                            .describe(
                                "What the report analyzes each run:\n\* `since_last_sent` (default) — everything since the previous successful scheduled delivery (gap-free; test\/manual sends don't move the anchor)\n\* `last_n_days` — a fixed trailing window of start_days_ago days\n\* `days_ago_range` — the explicit range from start_days_ago to end_days_ago days ago\n\n\* `since_last_sent` - Since last report\n\* `last_n_days` - Last N days\n\* `days_ago_range` - Between X and Y days ago"
                            ),
                        start_days_ago: zod
                            .number()
                            .min(1)
                            .max(subscriptionsPartialUpdateBodyAiPromptConfigOneWindowOneStartDaysAgoMax)
                            .nullish()
                            .describe(
                                "Lower bound of the analysis window, in days before the run. Required for 'last_n_days' (the N) and 'days_ago_range'; ignored for 'since_last_sent'. 1-365."
                            ),
                        end_days_ago: zod
                            .number()
                            .min(subscriptionsPartialUpdateBodyAiPromptConfigOneWindowOneEndDaysAgoMin)
                            .max(subscriptionsPartialUpdateBodyAiPromptConfigOneWindowOneEndDaysAgoMax)
                            .nullish()
                            .describe(
                                "Upper bound of the analysis window, in days before the run (0 = now). Required for 'days_ago_range' and must be less than start_days_ago; ignored for other modes. 0-365."
                            ),
                    })
                    .optional()
                    .describe(
                        "Analysis window for the report. Omitted = 'since_last_sent' (everything since the previous scheduled delivery)."
                    ),
            })
            .optional()
            .describe(
                "Configuration for AI report subscriptions (analysis window, future knobs). Only valid when resource_type is 'ai_prompt'. Replaced wholesale on writes."
            ),
        contexts: zod
            .array(
                zod.union([
                    zod.object({
                        dashboard_id: zod.number().min(1),
                    }),
                    zod.object({
                        insight_id: zod.number().min(1),
                    }),
                ])
            )
            .max(subscriptionsPartialUpdateBodyContextsMax)
            .optional()
            .describe(
                'Complete dashboard and insight context for an AI report. Omit on PATCH to preserve, pass an empty list to clear, or pass up to 3 items to replace all contexts.'
            ),
        proactive_config: zod
            .object({
                enabled: zod
                    .boolean()
                    .default(subscriptionsPartialUpdateBodyProactiveConfigOneEnabledDefault)
                    .describe('Whether future AI report deliveries may run proactive follow-up.'),
                repository: zod
                    .string()
                    .max(subscriptionsPartialUpdateBodyProactiveConfigOneRepositoryMax)
                    .nullish()
                    .describe(
                        'Exact repository in owner\/repository format. Required before draft pull requests are allowed.'
                    ),
                repository_integration_id: zod
                    .number()
                    .min(1)
                    .nullish()
                    .describe(
                        'Exact GitHub integration selected with the repository for draft pull request authorization.'
                    ),
                create_draft_pr: zod
                    .boolean()
                    .default(subscriptionsPartialUpdateBodyProactiveConfigOneCreateDraftPrDefault)
                    .describe('Whether Pulse may create one draft pull request on a future delivery.'),
                public_research_subject_id: zod
                    .uuid()
                    .nullish()
                    .describe('Optional eligible reviewed public research subject. Omit to disable public research.'),
            })
            .optional()
            .describe('Optional standing consent and limits for proactive follow-up on future AI report deliveries.'),
        target_type: zod
            .enum(['email', 'slack'])
            .describe('\* `email` - Email\n\* `slack` - Slack')
            .optional()
            .describe('Delivery channel: email or slack.\n\n\* `email` - Email\n\* `slack` - Slack'),
        target_value: zod
            .string()
            .optional()
            .describe('Recipient(s): comma-separated email addresses for email, or Slack channel name\/ID for slack.'),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('\* `daily` - Daily\n\* `weekly` - Weekly\n\* `monthly` - Monthly\n\* `yearly` - Yearly')
            .optional()
            .describe(
                'How often to deliver: daily, weekly, monthly, or yearly.\n\n\* `daily` - Daily\n\* `weekly` - Weekly\n\* `monthly` - Monthly\n\* `yearly` - Yearly'
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
                        '\* `monday` - Monday\n\* `tuesday` - Tuesday\n\* `wednesday` - Wednesday\n\* `thursday` - Thursday\n\* `friday` - Friday\n\* `saturday` - Saturday\n\* `sunday` - Sunday'
                    )
            )
            .nullish()
            .describe(
                'Days of week for daily or weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
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
        deleted: zod.boolean().optional().describe('Set to true to soft-delete. Subscriptions cannot be hard-deleted.'),
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
        invite_message: zod
            .string()
            .nullish()
            .describe('Optional message included in the invitation email when adding new recipients.'),
        send_test_now: zod
            .boolean()
            .optional()
            .describe(
                'Whether to immediately deliver the subscription once on save so the editor can confirm it looks right. Defaults to true on create. When omitted on update, a delivery is sent only if the edit changed what gets delivered (recipient, channel, source) or re-enabled the subscription. The recurring schedule is unaffected.'
            ),
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
 * Record an explicit adoption or dismissal for one advice-only proactive recommendation.
 */
export const SubscriptionsPulseActionsDecisionCreateBody = /* @__PURE__ */ zod.object({
    decision: zod
        .enum(['adopted', 'dismissed'])
        .describe('\* `adopted` - adopted\n\* `dismissed` - dismissed')
        .describe(
            'Whether to adopt or dismiss this advice-only recommendation.\n\n\* `adopted` - adopted\n\* `dismissed` - dismissed'
        ),
})

/**
 * Create the one inert experiment draft reserved for this staged Pulse task.
 */
export const subscriptionsPulseExperimentDraftsCreateBodyNameMax = 400

export const subscriptionsPulseExperimentDraftsCreateBodyHypothesisMax = 1200

export const subscriptionsPulseExperimentDraftsCreateBodyDescriptionDefault = ``
export const subscriptionsPulseExperimentDraftsCreateBodyDescriptionMax = 1200

export const subscriptionsPulseExperimentDraftsCreateBodyTargetDescriptionMax = 600

export const subscriptionsPulseExperimentDraftsCreateBodyVariantsItemKeyMax = 100

export const subscriptionsPulseExperimentDraftsCreateBodyVariantsItemKeyRegExp = new RegExp(
    '^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$'
)
export const subscriptionsPulseExperimentDraftsCreateBodyVariantsItemNameMax = 400

export const subscriptionsPulseExperimentDraftsCreateBodyVariantsMin = 2
export const subscriptionsPulseExperimentDraftsCreateBodyVariantsMax = 5

export const subscriptionsPulseExperimentDraftsCreateBodyPrimaryMetricOneEventNameMax = 400

export const subscriptionsPulseExperimentDraftsCreateBodySecondaryMetricsItemEventNameMax = 400

export const subscriptionsPulseExperimentDraftsCreateBodySecondaryMetricsMax = 9

export const SubscriptionsPulseExperimentDraftsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(subscriptionsPulseExperimentDraftsCreateBodyNameMax)
        .describe('Name for the new inert experiment draft.'),
    hypothesis: zod
        .string()
        .max(subscriptionsPulseExperimentDraftsCreateBodyHypothesisMax)
        .describe('Testable hypothesis recorded on the draft.'),
    description: zod
        .string()
        .max(subscriptionsPulseExperimentDraftsCreateBodyDescriptionMax)
        .default(subscriptionsPulseExperimentDraftsCreateBodyDescriptionDefault)
        .describe('Optional explanation of the proposed change.'),
    target_description: zod
        .string()
        .max(subscriptionsPulseExperimentDraftsCreateBodyTargetDescriptionMax)
        .describe('Plain-language audience or behavior targeted by the draft.'),
    variants: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .max(subscriptionsPulseExperimentDraftsCreateBodyVariantsItemKeyMax)
                    .regex(subscriptionsPulseExperimentDraftsCreateBodyVariantsItemKeyRegExp)
                    .describe('New variant key. It cannot identify an existing feature flag.'),
                name: zod
                    .string()
                    .max(subscriptionsPulseExperimentDraftsCreateBodyVariantsItemNameMax)
                    .describe('Display name for this variant.'),
            })
        )
        .min(subscriptionsPulseExperimentDraftsCreateBodyVariantsMin)
        .max(subscriptionsPulseExperimentDraftsCreateBodyVariantsMax)
        .describe('Two to five new variants. Rollout percentages are derived server-side.'),
    primary_metric: zod
        .object({
            kind: zod
                .enum(['event', 'action'])
                .describe('\* `event` - event\n\* `action` - action')
                .describe(
                    'Metric reference type. Pulse accepts only an event name or an action ID.\n\n\* `event` - event\n\* `action` - action'
                ),
            event_name: zod
                .string()
                .max(subscriptionsPulseExperimentDraftsCreateBodyPrimaryMetricOneEventNameMax)
                .optional()
                .describe('Existing event name when kind is event.'),
            action_id: zod.number().min(1).optional().describe('Existing project action ID when kind is action.'),
        })
        .describe('One existing event or action used as the primary metric.'),
    secondary_metrics: zod
        .array(
            zod.object({
                kind: zod
                    .enum(['event', 'action'])
                    .describe('\* `event` - event\n\* `action` - action')
                    .describe(
                        'Metric reference type. Pulse accepts only an event name or an action ID.\n\n\* `event` - event\n\* `action` - action'
                    ),
                event_name: zod
                    .string()
                    .max(subscriptionsPulseExperimentDraftsCreateBodySecondaryMetricsItemEventNameMax)
                    .optional()
                    .describe('Existing event name when kind is event.'),
                action_id: zod.number().min(1).optional().describe('Existing project action ID when kind is action.'),
            })
        )
        .max(subscriptionsPulseExperimentDraftsCreateBodySecondaryMetricsMax)
        .optional()
        .describe('Up to nine existing event or action references used as secondary metrics.'),
})
