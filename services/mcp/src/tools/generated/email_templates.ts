// AUTO-GENERATED from products/workflows/mcp/email_templates.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    MessagingTemplatesCreateBody,
    MessagingTemplatesListQueryParams,
    MessagingTemplatesPartialUpdateBody,
    MessagingTemplatesPartialUpdateParams,
    MessagingTemplatesRetrieveParams,
} from '@/generated/email_templates/api'
import { withUiApp } from '@/resources/ui-apps'
import { EmailTemplateDesignPatchSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, omitResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WorkflowsCreateEmailTemplateSchema = MessagingTemplatesCreateBody

const workflowsCreateEmailTemplate = (): ToolBase<
    typeof WorkflowsCreateEmailTemplateSchema,
    WithPostHogUrl<Schemas.MessageTemplate>
> => ({
    name: 'workflows-create-email-template',
    schema: WorkflowsCreateEmailTemplateSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsCreateEmailTemplateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.message_category !== undefined) {
            body['message_category'] = params.message_category
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        const result = await context.api.request<Schemas.MessageTemplate>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/`,
            body,
        })
        const filtered = omitResponseFields(result, ['content', 'created_by']) as typeof result
        return await withPostHogUrl(context, filtered, `/workflows/library/templates/${filtered.id}`)
    },
})

const WorkflowsGetEmailTemplateSchema = MessagingTemplatesRetrieveParams.omit({ project_id: true })

const workflowsGetEmailTemplate = (): ToolBase<
    typeof WorkflowsGetEmailTemplateSchema,
    WithPostHogUrl<Schemas.MessageTemplate>
> => ({
    name: 'workflows-get-email-template',
    schema: WorkflowsGetEmailTemplateSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsGetEmailTemplateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MessageTemplate>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = omitResponseFields(result, ['content.email.html', 'created_by']) as typeof result
        return await withPostHogUrl(context, filtered, `/workflows/library/templates/${filtered.id}`)
    },
})

const WorkflowsListEmailTemplatesSchema = MessagingTemplatesListQueryParams

const workflowsListEmailTemplates = (): ToolBase<
    typeof WorkflowsListEmailTemplatesSchema,
    WithPostHogUrl<Schemas.PaginatedMessageTemplateList>
> => ({
    name: 'workflows-list-email-templates',
    schema: WorkflowsListEmailTemplatesSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsListEmailTemplatesSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMessageTemplateList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) => omitResponseFields(item, ['content', 'created_by'])),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) =>
                        withPostHogUrl(context, item, `/workflows/library/templates/${item.id}`)
                    )
                ),
            },
            '/workflows/library/templates'
        )
    },
})

const WorkflowsPatchEmailTemplateSchema = EmailTemplateDesignPatchSchema

const workflowsPatchEmailTemplate = (): ToolBase<
    typeof WorkflowsPatchEmailTemplateSchema,
    Schemas.MessageTemplate
> => ({
    name: 'workflows-patch-email-template',
    schema: WorkflowsPatchEmailTemplateSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsPatchEmailTemplateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const parsedParams = WorkflowsPatchEmailTemplateSchema.parse(params)
        const { id, ...body } = parsedParams
        const result = await context.api.request<Schemas.MessageTemplate>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/${encodeURIComponent(String(id))}/design/`,
            body,
        })
        const filtered = omitResponseFields(result, ['content', 'created_by']) as typeof result
        return await withPostHogUrl(context, filtered, `/workflows/library/templates/${filtered.id}`)
    },
})

const WorkflowsShowEmailTemplateSchema = MessagingTemplatesRetrieveParams.omit({ project_id: true })

const workflowsShowEmailTemplate = (): ToolBase<
    typeof WorkflowsShowEmailTemplateSchema,
    WithPostHogUrl<Schemas.MessageTemplate>
> =>
    withUiApp('email-template', {
        name: 'workflows-show-email-template',
        schema: WorkflowsShowEmailTemplateSchema,
        handler: async (context: Context, params: z.infer<typeof WorkflowsShowEmailTemplateSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.MessageTemplate>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/${encodeURIComponent(String(params.id))}/`,
            })
            const filtered = omitResponseFields(result, ['content.email.design', 'created_by']) as typeof result
            return await withPostHogUrl(context, filtered, `/workflows/library/templates/${filtered.id}`)
        },
    })

const WorkflowsUpdateEmailTemplateSchema = MessagingTemplatesPartialUpdateParams.omit({ project_id: true }).extend(
    MessagingTemplatesPartialUpdateBody.shape
)

const workflowsUpdateEmailTemplate = (): ToolBase<
    typeof WorkflowsUpdateEmailTemplateSchema,
    WithPostHogUrl<Schemas.MessageTemplate>
> => ({
    name: 'workflows-update-email-template',
    schema: WorkflowsUpdateEmailTemplateSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsUpdateEmailTemplateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.message_category !== undefined) {
            body['message_category'] = params.message_category
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        const result = await context.api.request<Schemas.MessageTemplate>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        const filtered = omitResponseFields(result, ['content', 'created_by']) as typeof result
        return await withPostHogUrl(context, filtered, `/workflows/library/templates/${filtered.id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'workflows-create-email-template': workflowsCreateEmailTemplate,
    'workflows-get-email-template': workflowsGetEmailTemplate,
    'workflows-list-email-templates': workflowsListEmailTemplates,
    'workflows-patch-email-template': workflowsPatchEmailTemplate,
    'workflows-show-email-template': workflowsShowEmailTemplate,
    'workflows-update-email-template': workflowsUpdateEmailTemplate,
}
