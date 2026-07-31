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

export const RecurrenceIntervalEnumApi = zod
    .enum(['daily', 'weekly', 'monthly', 'yearly'])
    .describe('\* `daily` - Daily\n\* `weekly` - Weekly\n\* `monthly` - Monthly\n\* `yearly` - Yearly')

export type RecurrenceIntervalEnumApi = zod.input<typeof RecurrenceIntervalEnumApi>
export type RecurrenceIntervalEnumApiOutput = zod.output<typeof RecurrenceIntervalEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const ReminderStatusEnumApi = zod
    .enum(['active', 'completed', 'errored'])
    .describe('\* `active` - Active\n\* `completed` - Completed\n\* `errored` - Errored')

export type ReminderStatusEnumApi = zod.input<typeof ReminderStatusEnumApi>
export type ReminderStatusEnumApiOutput = zod.output<typeof ReminderStatusEnumApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

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

export const reminderApiTitleMax = 255

export const reminderApiResourceTypeMax = 50

export const reminderApiResourceIdMax = 200

export const reminderApiCronExpressionMax = 100

export const reminderApiTimezoneMax = 64

export const ReminderApi = zod.object({
    id: zod.uuid(),
    organization: zod.uuid().describe('ID of the organization this reminder belongs to. You must be a member of it.'),
    team: zod
        .number()
        .nullish()
        .describe(
            'Optional ID of the project this reminder is scoped to. Required when targeting a specific resource. Must belong to the chosen organization.'
        ),
    title: zod
        .string()
        .max(reminderApiTitleMax)
        .describe('Short text shown as the notification title when the reminder fires.'),
    message: zod.string().optional().describe('Optional longer body for the notification.'),
    resource_type: zod
        .string()
        .max(reminderApiResourceTypeMax)
        .nullish()
        .describe(
            'Optional PostHog resource this reminder is about. One of: dashboard, insight, experiment, feature_flag, survey, notebook, replay, error_tracking. Resources are project-scoped, so a team must be set when this is provided.'
        ),
    resource_id: zod
        .string()
        .max(reminderApiResourceIdMax)
        .nullish()
        .describe('ID of the referenced resource; must exist in the chosen project.'),
    scheduled_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('For a one-off reminder: when it should fire (ISO 8601, future).'),
    recurrence_interval: zod
        .union([RecurrenceIntervalEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'For a recurring reminder: daily, weekly, monthly, or yearly.\n\n\* `daily` - Daily\n\* `weekly` - Weekly\n\* `monthly` - Monthly\n\* `yearly` - Yearly'
        ),
    cron_expression: zod
        .string()
        .max(reminderApiCronExpressionMax)
        .nullish()
        .describe(
            "For a recurring reminder: a 5-field cron expression (e.g. '0 9 \* \* 1' = Mondays 9am). May fire at most 4 times per day. Mutually exclusive with recurrence_interval."
        ),
    timezone: zod
        .string()
        .max(reminderApiTimezoneMax)
        .optional()
        .describe(
            "IANA timezone the schedule resolves in (e.g. 'America\/New_York'). Defaults to the project timezone when a team is set, otherwise UTC."
        ),
    end_date: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Optional: recurring reminders stop (status=completed) after this time.'),
    next_fire_at: zod.iso.datetime({ offset: true }).nullable(),
    last_fired_at: zod.iso.datetime({ offset: true }).nullable(),
    status: ReminderStatusEnumApi,
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type ReminderApi = zod.input<typeof ReminderApi>
export type ReminderApiOutput = zod.output<typeof ReminderApi>

export const PaginatedReminderListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ReminderApi),
})

export type PaginatedReminderListApi = zod.input<typeof PaginatedReminderListApi>
export type PaginatedReminderListApiOutput = zod.output<typeof PaginatedReminderListApi>

export const patchedReminderApiTitleMax = 255

export const patchedReminderApiResourceTypeMax = 50

export const patchedReminderApiResourceIdMax = 200

export const patchedReminderApiCronExpressionMax = 100

export const patchedReminderApiTimezoneMax = 64

export const PatchedReminderApi = zod.object({
    id: zod.uuid().optional(),
    organization: zod
        .uuid()
        .optional()
        .describe('ID of the organization this reminder belongs to. You must be a member of it.'),
    team: zod
        .number()
        .nullish()
        .describe(
            'Optional ID of the project this reminder is scoped to. Required when targeting a specific resource. Must belong to the chosen organization.'
        ),
    title: zod
        .string()
        .max(patchedReminderApiTitleMax)
        .optional()
        .describe('Short text shown as the notification title when the reminder fires.'),
    message: zod.string().optional().describe('Optional longer body for the notification.'),
    resource_type: zod
        .string()
        .max(patchedReminderApiResourceTypeMax)
        .nullish()
        .describe(
            'Optional PostHog resource this reminder is about. One of: dashboard, insight, experiment, feature_flag, survey, notebook, replay, error_tracking. Resources are project-scoped, so a team must be set when this is provided.'
        ),
    resource_id: zod
        .string()
        .max(patchedReminderApiResourceIdMax)
        .nullish()
        .describe('ID of the referenced resource; must exist in the chosen project.'),
    scheduled_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('For a one-off reminder: when it should fire (ISO 8601, future).'),
    recurrence_interval: zod
        .union([RecurrenceIntervalEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'For a recurring reminder: daily, weekly, monthly, or yearly.\n\n\* `daily` - Daily\n\* `weekly` - Weekly\n\* `monthly` - Monthly\n\* `yearly` - Yearly'
        ),
    cron_expression: zod
        .string()
        .max(patchedReminderApiCronExpressionMax)
        .nullish()
        .describe(
            "For a recurring reminder: a 5-field cron expression (e.g. '0 9 \* \* 1' = Mondays 9am). May fire at most 4 times per day. Mutually exclusive with recurrence_interval."
        ),
    timezone: zod
        .string()
        .max(patchedReminderApiTimezoneMax)
        .optional()
        .describe(
            "IANA timezone the schedule resolves in (e.g. 'America\/New_York'). Defaults to the project timezone when a team is set, otherwise UTC."
        ),
    end_date: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Optional: recurring reminders stop (status=completed) after this time.'),
    next_fire_at: zod.iso.datetime({ offset: true }).nullish(),
    last_fired_at: zod.iso.datetime({ offset: true }).nullish(),
    status: ReminderStatusEnumApi.optional(),
    created_by: UserBasicApi.optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedReminderApi = zod.input<typeof PatchedReminderApi>
export type PatchedReminderApiOutput = zod.output<typeof PatchedReminderApi>
