// AUTO-GENERATED from products/reminders/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    RemindersCreateBody,
    RemindersDestroyParams,
    RemindersListQueryParams,
    RemindersPartialUpdateBody,
    RemindersPartialUpdateParams,
    RemindersRetrieveParams,
} from '@/generated/reminders/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ReminderCreateSchema = RemindersCreateBody

const reminderCreate = (): ToolBase<typeof ReminderCreateSchema, Schemas.Reminder> => ({
    name: 'reminder-create',
    schema: ReminderCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ReminderCreateSchema>) => {
        const body: Record<string, unknown> = {}
        if (params.organization !== undefined) {
            body['organization'] = params.organization
        }
        if (params.team !== undefined) {
            body['team'] = params.team
        }
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.message !== undefined) {
            body['message'] = params.message
        }
        if (params.resource_type !== undefined) {
            body['resource_type'] = params.resource_type
        }
        if (params.resource_id !== undefined) {
            body['resource_id'] = params.resource_id
        }
        if (params.scheduled_at !== undefined) {
            body['scheduled_at'] = params.scheduled_at
        }
        if (params.recurrence_interval !== undefined) {
            body['recurrence_interval'] = params.recurrence_interval
        }
        if (params.cron_expression !== undefined) {
            body['cron_expression'] = params.cron_expression
        }
        if (params.timezone !== undefined) {
            body['timezone'] = params.timezone
        }
        if (params.end_date !== undefined) {
            body['end_date'] = params.end_date
        }
        const result = await context.api.request<Schemas.Reminder>({
            method: 'POST',
            path: `/api/reminders/`,
            body,
        })
        return result
    },
})

const ReminderDeleteSchema = RemindersDestroyParams

const reminderDelete = (): ToolBase<typeof ReminderDeleteSchema, Schemas.Reminder> => ({
    name: 'reminder-delete',
    schema: ReminderDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof ReminderDeleteSchema>) => {
        const result = await context.api.request<Schemas.Reminder>({
            method: 'PATCH',
            path: `/api/reminders/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const ReminderGetSchema = RemindersRetrieveParams

const reminderGet = (): ToolBase<typeof ReminderGetSchema, Schemas.Reminder> => ({
    name: 'reminder-get',
    schema: ReminderGetSchema,
    handler: async (context: Context, params: z.infer<typeof ReminderGetSchema>) => {
        const result = await context.api.request<Schemas.Reminder>({
            method: 'GET',
            path: `/api/reminders/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ReminderUpdateSchema = RemindersPartialUpdateParams.extend(RemindersPartialUpdateBody.shape)

const reminderUpdate = (): ToolBase<typeof ReminderUpdateSchema, Schemas.Reminder> => ({
    name: 'reminder-update',
    schema: ReminderUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ReminderUpdateSchema>) => {
        const body: Record<string, unknown> = {}
        if (params.organization !== undefined) {
            body['organization'] = params.organization
        }
        if (params.team !== undefined) {
            body['team'] = params.team
        }
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.message !== undefined) {
            body['message'] = params.message
        }
        if (params.resource_type !== undefined) {
            body['resource_type'] = params.resource_type
        }
        if (params.resource_id !== undefined) {
            body['resource_id'] = params.resource_id
        }
        if (params.scheduled_at !== undefined) {
            body['scheduled_at'] = params.scheduled_at
        }
        if (params.recurrence_interval !== undefined) {
            body['recurrence_interval'] = params.recurrence_interval
        }
        if (params.cron_expression !== undefined) {
            body['cron_expression'] = params.cron_expression
        }
        if (params.timezone !== undefined) {
            body['timezone'] = params.timezone
        }
        if (params.end_date !== undefined) {
            body['end_date'] = params.end_date
        }
        const result = await context.api.request<Schemas.Reminder>({
            method: 'PATCH',
            path: `/api/reminders/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const RemindersListSchema = RemindersListQueryParams

const remindersList = (): ToolBase<typeof RemindersListSchema, WithPostHogUrl<Schemas.PaginatedReminderList>> => ({
    name: 'reminders-list',
    schema: RemindersListSchema,
    handler: async (context: Context, params: z.infer<typeof RemindersListSchema>) => {
        const result = await context.api.request<Schemas.PaginatedReminderList>({
            method: 'GET',
            path: `/api/reminders/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'reminder-create': reminderCreate,
    'reminder-delete': reminderDelete,
    'reminder-get': reminderGet,
    'reminder-update': reminderUpdate,
    'reminders-list': remindersList,
}
