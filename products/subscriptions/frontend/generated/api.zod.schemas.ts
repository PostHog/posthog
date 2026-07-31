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

export const ResourceTypeEnumApi = zod
    .enum(['insight', 'dashboard', 'ai_prompt'])
    .describe('\* `insight` - Insight\n\* `dashboard` - Dashboard\n\* `ai_prompt` - AI prompt')

export type ResourceTypeEnumApi = zod.input<typeof ResourceTypeEnumApi>
export type ResourceTypeEnumApiOutput = zod.output<typeof ResourceTypeEnumApi>

export const AIWindowConfigModeEnumApi = zod
    .enum(['since_last_sent', 'last_n_days', 'days_ago_range'])
    .describe(
        '\* `since_last_sent` - Since last report\n\* `last_n_days` - Last N days\n\* `days_ago_range` - Between X and Y days ago'
    )

export type AIWindowConfigModeEnumApi = zod.input<typeof AIWindowConfigModeEnumApi>
export type AIWindowConfigModeEnumApiOutput = zod.output<typeof AIWindowConfigModeEnumApi>

export const aIWindowConfigApiModeDefault = `since_last_sent`
export const aIWindowConfigApiStartDaysAgoMax = 365

export const aIWindowConfigApiEndDaysAgoMin = 0
export const aIWindowConfigApiEndDaysAgoMax = 365

export const AIWindowConfigApi = zod.object({
    mode: AIWindowConfigModeEnumApi.default(aIWindowConfigApiModeDefault).describe(
        "What the report analyzes each run:\n\* `since_last_sent` (default) — everything since the previous successful scheduled delivery (gap-free; test\/manual sends don't move the anchor)\n\* `last_n_days` — a fixed trailing window of start_days_ago days\n\* `days_ago_range` — the explicit range from start_days_ago to end_days_ago days ago\n\n\* `since_last_sent` - Since last report\n\* `last_n_days` - Last N days\n\* `days_ago_range` - Between X and Y days ago"
    ),
    start_days_ago: zod
        .number()
        .min(1)
        .max(aIWindowConfigApiStartDaysAgoMax)
        .nullish()
        .describe(
            "Lower bound of the analysis window, in days before the run. Required for 'last_n_days' (the N) and 'days_ago_range'; ignored for 'since_last_sent'. 1-365."
        ),
    end_days_ago: zod
        .number()
        .min(aIWindowConfigApiEndDaysAgoMin)
        .max(aIWindowConfigApiEndDaysAgoMax)
        .nullish()
        .describe(
            "Upper bound of the analysis window, in days before the run (0 = now). Required for 'days_ago_range' and must be less than start_days_ago; ignored for other modes. 0-365."
        ),
})

export type AIWindowConfigApi = zod.input<typeof AIWindowConfigApi>
export type AIWindowConfigApiOutput = zod.output<typeof AIWindowConfigApi>

export const AIPromptConfigApi = zod.object({
    window: AIWindowConfigApi.optional().describe(
        "Analysis window for the report. Omitted = 'since_last_sent' (everything since the previous scheduled delivery)."
    ),
})

export type AIPromptConfigApi = zod.input<typeof AIPromptConfigApi>
export type AIPromptConfigApiOutput = zod.output<typeof AIPromptConfigApi>

export const TargetTypeEnumApi = zod.enum(['email', 'slack']).describe('\* `email` - Email\n\* `slack` - Slack')

export type TargetTypeEnumApi = zod.input<typeof TargetTypeEnumApi>
export type TargetTypeEnumApiOutput = zod.output<typeof TargetTypeEnumApi>

export const RecurrenceIntervalEnumApi = zod
    .enum(['daily', 'weekly', 'monthly', 'yearly'])
    .describe('\* `daily` - Daily\n\* `weekly` - Weekly\n\* `monthly` - Monthly\n\* `yearly` - Yearly')

export type RecurrenceIntervalEnumApi = zod.input<typeof RecurrenceIntervalEnumApi>
export type RecurrenceIntervalEnumApiOutput = zod.output<typeof RecurrenceIntervalEnumApi>

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

export const subscriptionApiIntervalMax = 2147483647

export const subscriptionApiBysetposMin = -2147483648
export const subscriptionApiBysetposMax = 2147483647

export const subscriptionApiCountMin = -2147483648
export const subscriptionApiCountMax = 2147483647

export const subscriptionApiTitleMax = 100

export const subscriptionApiSummaryPromptGuideMax = 500

export const SubscriptionApi = zod
    .object({
        id: zod.number(),
        resource_type: ResourceTypeEnumApi.describe(
            "What the subscription delivers: 'insight' (snapshot of one insight), 'dashboard' (snapshot of one dashboard), or 'ai_prompt' (LLM-generated report). Read-only — derived from the populated target (insight → insight, dashboard → dashboard, prompt → ai_prompt).\n\n\* `insight` - Insight\n\* `dashboard` - Dashboard\n\* `ai_prompt` - AI prompt"
        ),
        dashboard: zod
            .number()
            .nullish()
            .describe('Dashboard ID to subscribe to (mutually exclusive with insight on create).'),
        insight: zod
            .number()
            .nullish()
            .describe('Insight ID to subscribe to (mutually exclusive with dashboard on create).'),
        insight_short_id: zod.string().nullable(),
        resource_name: zod.string().nullable(),
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
        ai_prompt_config: AIPromptConfigApi.optional().describe(
            "Configuration for AI report subscriptions (analysis window, future knobs). Only valid when resource_type is 'ai_prompt'. Replaced wholesale on writes."
        ),
        target_type: TargetTypeEnumApi.describe(
            'Delivery channel: email or slack.\n\n\* `email` - Email\n\* `slack` - Slack'
        ),
        target_value: zod
            .string()
            .describe('Recipient(s): comma-separated email addresses for email, or Slack channel name\/ID for slack.'),
        frequency: RecurrenceIntervalEnumApi.describe(
            'How often to deliver: daily, weekly, monthly, or yearly.\n\n\* `daily` - Daily\n\* `weekly` - Weekly\n\* `monthly` - Monthly\n\* `yearly` - Yearly'
        ),
        interval: zod
            .number()
            .min(1)
            .max(subscriptionApiIntervalMax)
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
                'Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
            ),
        bysetpos: zod
            .number()
            .min(subscriptionApiBysetposMin)
            .max(subscriptionApiBysetposMax)
            .nullish()
            .describe('Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).'),
        count: zod
            .number()
            .min(subscriptionApiCountMin)
            .max(subscriptionApiCountMax)
            .nullish()
            .describe('Total number of deliveries before the subscription stops. Null for unlimited.'),
        start_date: zod.iso.datetime({ offset: true }).describe('When to start delivering (ISO 8601 datetime).'),
        until_date: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('When to stop delivering (ISO 8601 datetime). Null for indefinite.'),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
        deleted: zod.boolean().optional().describe('Set to true to soft-delete. Subscriptions cannot be hard-deleted.'),
        enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether the subscription is active. Set to false to pause delivery without deleting. Auto-set to false when the delivery integration becomes invalid.'
            ),
        title: zod
            .string()
            .max(subscriptionApiTitleMax)
            .nullish()
            .describe('Human-readable name for this subscription.'),
        summary: zod.string().describe("Human-readable schedule summary, e.g. 'sent daily'."),
        next_delivery_date: zod.iso.datetime({ offset: true }).nullable(),
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
            .max(subscriptionApiSummaryPromptGuideMax)
            .optional()
            .describe(
                'Optional free-text guidance (max 500 chars) steering the AI summary, e.g. which metrics to emphasize. Only settable when AI summary context is enabled for the organization; clearing it (empty string) is always allowed.'
            ),
    })
    .describe('Standard Subscription serializer.')

export type SubscriptionApi = zod.input<typeof SubscriptionApi>
export type SubscriptionApiOutput = zod.output<typeof SubscriptionApi>

export const PaginatedSubscriptionListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SubscriptionApi),
})

export type PaginatedSubscriptionListApi = zod.input<typeof PaginatedSubscriptionListApi>
export type PaginatedSubscriptionListApiOutput = zod.output<typeof PaginatedSubscriptionListApi>

export const patchedSubscriptionApiIntervalMax = 2147483647

export const patchedSubscriptionApiBysetposMin = -2147483648
export const patchedSubscriptionApiBysetposMax = 2147483647

export const patchedSubscriptionApiCountMin = -2147483648
export const patchedSubscriptionApiCountMax = 2147483647

export const patchedSubscriptionApiTitleMax = 100

export const patchedSubscriptionApiSummaryPromptGuideMax = 500

export const PatchedSubscriptionApi = zod
    .object({
        id: zod.number().optional(),
        resource_type: ResourceTypeEnumApi.optional().describe(
            "What the subscription delivers: 'insight' (snapshot of one insight), 'dashboard' (snapshot of one dashboard), or 'ai_prompt' (LLM-generated report). Read-only — derived from the populated target (insight → insight, dashboard → dashboard, prompt → ai_prompt).\n\n\* `insight` - Insight\n\* `dashboard` - Dashboard\n\* `ai_prompt` - AI prompt"
        ),
        dashboard: zod
            .number()
            .nullish()
            .describe('Dashboard ID to subscribe to (mutually exclusive with insight on create).'),
        insight: zod
            .number()
            .nullish()
            .describe('Insight ID to subscribe to (mutually exclusive with dashboard on create).'),
        insight_short_id: zod.string().nullish(),
        resource_name: zod.string().nullish(),
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
        ai_prompt_config: AIPromptConfigApi.optional().describe(
            "Configuration for AI report subscriptions (analysis window, future knobs). Only valid when resource_type is 'ai_prompt'. Replaced wholesale on writes."
        ),
        target_type: TargetTypeEnumApi.optional().describe(
            'Delivery channel: email or slack.\n\n\* `email` - Email\n\* `slack` - Slack'
        ),
        target_value: zod
            .string()
            .optional()
            .describe('Recipient(s): comma-separated email addresses for email, or Slack channel name\/ID for slack.'),
        frequency: RecurrenceIntervalEnumApi.optional().describe(
            'How often to deliver: daily, weekly, monthly, or yearly.\n\n\* `daily` - Daily\n\* `weekly` - Weekly\n\* `monthly` - Monthly\n\* `yearly` - Yearly'
        ),
        interval: zod
            .number()
            .min(1)
            .max(patchedSubscriptionApiIntervalMax)
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
                'Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
            ),
        bysetpos: zod
            .number()
            .min(patchedSubscriptionApiBysetposMin)
            .max(patchedSubscriptionApiBysetposMax)
            .nullish()
            .describe('Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).'),
        count: zod
            .number()
            .min(patchedSubscriptionApiCountMin)
            .max(patchedSubscriptionApiCountMax)
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
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: UserBasicApi.optional(),
        deleted: zod.boolean().optional().describe('Set to true to soft-delete. Subscriptions cannot be hard-deleted.'),
        enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether the subscription is active. Set to false to pause delivery without deleting. Auto-set to false when the delivery integration becomes invalid.'
            ),
        title: zod
            .string()
            .max(patchedSubscriptionApiTitleMax)
            .nullish()
            .describe('Human-readable name for this subscription.'),
        summary: zod.string().optional().describe("Human-readable schedule summary, e.g. 'sent daily'."),
        next_delivery_date: zod.iso.datetime({ offset: true }).nullish(),
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
            .max(patchedSubscriptionApiSummaryPromptGuideMax)
            .optional()
            .describe(
                'Optional free-text guidance (max 500 chars) steering the AI summary, e.g. which metrics to emphasize. Only settable when AI summary context is enabled for the organization; clearing it (empty string) is always allowed.'
            ),
    })
    .describe('Standard Subscription serializer.')

export type PatchedSubscriptionApi = zod.input<typeof PatchedSubscriptionApi>
export type PatchedSubscriptionApiOutput = zod.output<typeof PatchedSubscriptionApi>

export const SubscriptionDeliveryStatusEnumApi = zod
    .enum(['starting', 'completed', 'failed', 'skipped'])
    .describe('\* `starting` - Starting\n\* `completed` - Completed\n\* `failed` - Failed\n\* `skipped` - Skipped')

export type SubscriptionDeliveryStatusEnumApi = zod.input<typeof SubscriptionDeliveryStatusEnumApi>
export type SubscriptionDeliveryStatusEnumApiOutput = zod.output<typeof SubscriptionDeliveryStatusEnumApi>

export const AIReportQueryDiagnosticApi = zod.object({
    description: zod.string().describe('What this query step was meant to compute.'),
    hogql: zod.string().describe('The HogQL the assistant generated for this step.'),
    ok: zod.boolean().describe('Whether the query ran successfully.'),
    error_type: zod.string().nullable().describe('Exception class name when the query failed; null on success.'),
    human_readable_error: zod
        .string()
        .nullish()
        .describe(
            'Human-readable failure reason, present only for query errors safe to surface to the subscription owner (e.g. an unresolved field name); null on success and for internal errors, which expose error_type only.'
        ),
})

export type AIReportQueryDiagnosticApi = zod.input<typeof AIReportQueryDiagnosticApi>
export type AIReportQueryDiagnosticApiOutput = zod.output<typeof AIReportQueryDiagnosticApi>

export const subscriptionDeliveryApiExportedAssetIdsItemMin = -2147483648
export const subscriptionDeliveryApiExportedAssetIdsItemMax = 2147483647

export const SubscriptionDeliveryApi = zod.object({
    id: zod.uuid().describe('Primary key for this delivery row.'),
    subscription: zod.number().describe('Parent subscription id.'),
    temporal_workflow_id: zod.string().describe('Temporal workflow id for this delivery run.'),
    idempotency_key: zod.string().describe('Dedupes activity retries for the same logical run.'),
    trigger_type: zod.string().describe('Why the run started (e.g. scheduled, manual, subscription update).'),
    scheduled_at: zod.iso.datetime({ offset: true }).nullable().describe('Planned send time when applicable.'),
    target_type: zod.string().describe('Channel snapshot at send time (email or slack).'),
    target_value: zod.string().describe('Destination snapshot at send time (emails, channel id, URL).'),
    exported_asset_ids: zod
        .array(
            zod
                .number()
                .min(subscriptionDeliveryApiExportedAssetIdsItemMin)
                .max(subscriptionDeliveryApiExportedAssetIdsItemMax)
        )
        .describe('ExportedAsset ids generated for this send.'),
    content_snapshot: zod
        .unknown()
        .describe(
            'Snapshot at send time: dashboard metadata, total_insight_count, and per-exported-insight entries (id, short_id, name, query_hash, cache_key, query_results, optional query_error).'
        ),
    recipient_results: zod
        .unknown()
        .describe('Per-destination outcomes; items use status success, failed, or partial.'),
    status: SubscriptionDeliveryStatusEnumApi.describe(
        'Overall run status: starting, completed, failed, or skipped.\n\n\* `starting` - Starting\n\* `completed` - Completed\n\* `failed` - Failed\n\* `skipped` - Skipped'
    ),
    error: zod.unknown().describe('Top-level failure payload when status is failed, if any.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the delivery row was created.'),
    last_updated_at: zod.iso.datetime({ offset: true }).describe('Last ORM update to this row.'),
    finished_at: zod.iso.datetime({ offset: true }).nullable().describe('When the run finished, if applicable.'),
    change_summary: zod
        .string()
        .nullable()
        .describe('AI-generated summary included in this delivery, when one was produced.'),
    ai_report: zod
        .string()
        .nullable()
        .describe(
            'AI-generated report markdown delivered by this run. Null for non-AI deliveries or runs without a persisted report.'
        ),
    ai_report_diagnostics: zod
        .array(AIReportQueryDiagnosticApi)
        .nullable()
        .describe(
            'Per-step query diagnostics (generated HogQL + failure type) for this report. Null for non-AI deliveries or runs without persisted diagnostics.'
        ),
    ai_report_prompt: zod
        .string()
        .nullable()
        .describe(
            "The subscription's prompt as it was when this report was generated. Null for older deliveries and non-AI deliveries."
        ),
})

export type SubscriptionDeliveryApi = zod.input<typeof SubscriptionDeliveryApi>
export type SubscriptionDeliveryApiOutput = zod.output<typeof SubscriptionDeliveryApi>

export const PaginatedSubscriptionDeliveryListApi = zod.object({
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SubscriptionDeliveryApi),
})

export type PaginatedSubscriptionDeliveryListApi = zod.input<typeof PaginatedSubscriptionDeliveryListApi>
export type PaginatedSubscriptionDeliveryListApiOutput = zod.output<typeof PaginatedSubscriptionDeliveryListApi>
