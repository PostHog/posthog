// AUTO-GENERATED from definitions/actions.yaml — do not edit
import { z } from 'zod'

import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ActionGetSchema = z.object({
    actionId: z.number().int().positive().describe('The ID of the action to retrieve'),
})

const actionGet = (): ToolBase<typeof ActionGetSchema> => ({
    name: 'action-get',
    schema: ActionGetSchema,
    handler: async (context: Context, params: z.infer<typeof ActionGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
            method: 'GET',
            path: `/api/projects/${projectId}/actions/${params.actionId}/`,
        })
        return {
            ...(result as any),
            url: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${(result as any).id}`,
        }
    },
})

const ActionsGetAllSchema = z.object({
    limit: z.number().int().optional().describe('Maximum number of actions to return'),
    offset: z.number().int().optional().describe('Number of actions to skip for pagination'),
})

const actionsGetAll = (): ToolBase<typeof ActionsGetAllSchema> => ({
    name: 'actions-get-all',
    schema: ActionsGetAllSchema,
    handler: async (context: Context, params: z.infer<typeof ActionsGetAllSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
            method: 'GET',
            path: `/api/projects/${projectId}/actions/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const items = (result as any).results ?? result
        return (items as any[]).map((item: any) => ({
            ...item,
            url: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${item.id}`,
        }))
    },
})

const ActionCreateSchema = z.object({
    name: z.string().min(1).describe('Name of the action (must be unique within the project)'),
    description: z.string().optional().describe('Description of what this action represents'),
    steps: z
        .array(
            z.object({
                event: z
                    .string()
                    .optional()
                    .describe("Event name (e.g., '$pageview', '$autocapture', or custom event name)"),
                properties: z.any().optional().describe('Event properties to filter on'),
                tag_name: z.string().optional().describe("HTML tag name to match (e.g., 'button', 'a', 'input')"),
                text: z.string().optional().describe('Element text content to match'),
                text_matching: z.string().optional().describe("How to match text: 'contains', 'regex', or 'exact'"),
                href: z.string().optional().describe('Link href attribute to match'),
                href_matching: z.string().optional().describe("How to match href: 'contains', 'regex', or 'exact'"),
                selector: z.string().optional().describe('CSS selector to match element'),
                url: z.string().optional().describe('Page URL to match'),
                url_matching: z.string().optional().describe("How to match URL: 'contains', 'regex', or 'exact'"),
            })
        )
        .min(1)
        .describe('Action steps — each defines a trigger condition. Multiple steps are OR-ed together.'),
    tags: z.array(z.string()).optional().describe('Tags for organizing actions'),
    postToSlack: z
        .boolean()
        .default(false)
        .optional()
        .describe('Whether to post to Slack when this action is triggered'),
    slackMessageFormat: z.string().optional().describe('Custom Slack message format'),
})

const actionCreate = (): ToolBase<typeof ActionCreateSchema> => ({
    name: 'action-create',
    schema: ActionCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ActionCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.steps !== undefined) {
            body['steps'] = params.steps
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.postToSlack !== undefined) {
            body['post_to_slack'] = params.postToSlack
        }
        if (params.slackMessageFormat !== undefined) {
            body['slack_message_format'] = params.slackMessageFormat
        }
        const result = await context.api.request({
            method: 'POST',
            path: `/api/projects/${projectId}/actions/`,
            body,
        })
        return {
            ...(result as any),
            url: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${(result as any).id}`,
        }
    },
})

const ActionUpdateSchema = z.object({
    actionId: z.number().int().positive().describe('The ID of the action to update'),
    name: z.string().optional().describe('Updated action name'),
    description: z.string().optional().nullable().describe('Updated description'),
    steps: z
        .array(
            z.object({
                event: z.string().optional().describe('Event name'),
                properties: z.any().optional().describe('Event properties to filter on'),
                tag_name: z.string().optional().describe('HTML tag name to match'),
                text: z.string().optional().describe('Element text content to match'),
                text_matching: z.string().optional().describe('How to match text'),
                href: z.string().optional().describe('Link href to match'),
                href_matching: z.string().optional().describe('How to match href'),
                selector: z.string().optional().describe('CSS selector'),
                url: z.string().optional().describe('Page URL to match'),
                url_matching: z.string().optional().describe('How to match URL'),
            })
        )
        .optional()
        .describe('Updated action steps'),
    tags: z.array(z.string()).optional().describe('Updated tags'),
    postToSlack: z.boolean().optional().describe('Whether to post to Slack'),
    slackMessageFormat: z.string().optional().describe('Custom Slack message format'),
    pinnedAt: z.string().optional().nullable().describe('Pin timestamp (set to pin, null to unpin)'),
})

const actionUpdate = (): ToolBase<typeof ActionUpdateSchema> => ({
    name: 'action-update',
    schema: ActionUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ActionUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.steps !== undefined) {
            body['steps'] = params.steps
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.postToSlack !== undefined) {
            body['post_to_slack'] = params.postToSlack
        }
        if (params.slackMessageFormat !== undefined) {
            body['slack_message_format'] = params.slackMessageFormat
        }
        if (params.pinnedAt !== undefined) {
            body['pinned_at'] = params.pinnedAt
        }
        const result = await context.api.request({
            method: 'PATCH',
            path: `/api/projects/${projectId}/actions/${params.actionId}/`,
            body,
        })
        return {
            ...(result as any),
            url: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${(result as any).id}`,
        }
    },
})

const ActionDeleteSchema = z.object({
    actionId: z.number().int().positive().describe('The ID of the action to delete'),
})

const actionDelete = (): ToolBase<typeof ActionDeleteSchema> => ({
    name: 'action-delete',
    schema: ActionDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof ActionDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
            method: 'DELETE',
            path: `/api/projects/${projectId}/actions/${params.actionId}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'action-get': actionGet,
    'actions-get-all': actionsGetAll,
    'action-create': actionCreate,
    'action-update': actionUpdate,
    'action-delete': actionDelete,
}
