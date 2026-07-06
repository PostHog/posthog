/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const RemindersListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const remindersCreateBodyTitleMax = 255

export const remindersCreateBodyResourceTypeMax = 50

export const remindersCreateBodyResourceIdMax = 200

export const remindersCreateBodyCronExpressionMax = 100

export const remindersCreateBodyTimezoneMax = 64

export const RemindersCreateBody = /* @__PURE__ */ zod.object({
    organization: zod.string().describe('ID of the organization this reminder belongs to. You must be a member of it.'),
    team: zod
        .number()
        .nullish()
        .describe(
            'Optional ID of the project this reminder is scoped to. Required when targeting a specific resource. Must belong to the chosen organization.'
        ),
    title: zod
        .string()
        .max(remindersCreateBodyTitleMax)
        .describe('Short text shown as the notification title when the reminder fires.'),
    message: zod.string().optional().describe('Optional longer body for the notification.'),
    resource_type: zod
        .string()
        .max(remindersCreateBodyResourceTypeMax)
        .nullish()
        .describe(
            'Optional PostHog resource this reminder is about. One of: dashboard, insight, experiment, feature_flag, survey, notebook, replay, error_tracking. Resources are project-scoped, so a team must be set when this is provided.'
        ),
    resource_id: zod
        .string()
        .max(remindersCreateBodyResourceIdMax)
        .nullish()
        .describe('ID of the referenced resource; must exist in the chosen project.'),
    scheduled_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('For a one-off reminder: when it should fire (ISO 8601, future).'),
    recurrence_interval: zod
        .union([
            zod
                .enum(['daily', 'weekly', 'monthly', 'yearly'])
                .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional()
        .describe(
            'For a recurring reminder: daily, weekly, monthly, or yearly.\n\n* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'
        ),
    cron_expression: zod
        .string()
        .max(remindersCreateBodyCronExpressionMax)
        .nullish()
        .describe(
            "For a recurring reminder: a 5-field cron expression (e.g. '0 9 * * 1' = Mondays 9am). May fire at most 4 times per day. Mutually exclusive with recurrence_interval."
        ),
    timezone: zod
        .string()
        .max(remindersCreateBodyTimezoneMax)
        .optional()
        .describe(
            "IANA timezone the schedule resolves in (e.g. 'America/New_York'). Defaults to the project timezone when a team is set, otherwise UTC."
        ),
    end_date: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Optional: recurring reminders stop (status=completed) after this time.'),
})

export const RemindersRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this reminder.'),
})

export const RemindersPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this reminder.'),
})

export const remindersPartialUpdateBodyTitleMax = 255

export const remindersPartialUpdateBodyResourceTypeMax = 50

export const remindersPartialUpdateBodyResourceIdMax = 200

export const remindersPartialUpdateBodyCronExpressionMax = 100

export const remindersPartialUpdateBodyTimezoneMax = 64

export const RemindersPartialUpdateBody = /* @__PURE__ */ zod.object({
    organization: zod
        .string()
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
        .max(remindersPartialUpdateBodyTitleMax)
        .optional()
        .describe('Short text shown as the notification title when the reminder fires.'),
    message: zod.string().optional().describe('Optional longer body for the notification.'),
    resource_type: zod
        .string()
        .max(remindersPartialUpdateBodyResourceTypeMax)
        .nullish()
        .describe(
            'Optional PostHog resource this reminder is about. One of: dashboard, insight, experiment, feature_flag, survey, notebook, replay, error_tracking. Resources are project-scoped, so a team must be set when this is provided.'
        ),
    resource_id: zod
        .string()
        .max(remindersPartialUpdateBodyResourceIdMax)
        .nullish()
        .describe('ID of the referenced resource; must exist in the chosen project.'),
    scheduled_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('For a one-off reminder: when it should fire (ISO 8601, future).'),
    recurrence_interval: zod
        .union([
            zod
                .enum(['daily', 'weekly', 'monthly', 'yearly'])
                .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional()
        .describe(
            'For a recurring reminder: daily, weekly, monthly, or yearly.\n\n* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'
        ),
    cron_expression: zod
        .string()
        .max(remindersPartialUpdateBodyCronExpressionMax)
        .nullish()
        .describe(
            "For a recurring reminder: a 5-field cron expression (e.g. '0 9 * * 1' = Mondays 9am). May fire at most 4 times per day. Mutually exclusive with recurrence_interval."
        ),
    timezone: zod
        .string()
        .max(remindersPartialUpdateBodyTimezoneMax)
        .optional()
        .describe(
            "IANA timezone the schedule resolves in (e.g. 'America/New_York'). Defaults to the project timezone when a team is set, otherwise UTC."
        ),
    end_date: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Optional: recurring reminders stop (status=completed) after this time.'),
})

export const RemindersDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this reminder.'),
})
