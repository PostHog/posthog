// AUTO-GENERATED from products/workflows/mcp/email_templates.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/email_templates/api'
import { withUiApp } from '@/resources/ui-apps'
import { EmailTemplateDesignPatchSchema } from '@/schema/tool-inputs'
import { getConfirmedActionRuntime } from '@/tools/confirmed-action-registry'
import {
    executeConfirmedAction,
    prepareConfirmedAction,
    type PrepareConfirmedActionResult,
} from '@/tools/confirmed-action-runtime'
import { withPostHogUrl, omitResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WorkflowsCreateEmailTemplateSchema = () => {
    const MessagingTemplatesCreateBody = orvalSchemas.MessagingTemplatesCreateBody()
    return MessagingTemplatesCreateBody
}

const workflowsCreateEmailTemplate = (): ToolBase<
    ReturnType<typeof WorkflowsCreateEmailTemplateSchema>,
    WithPostHogUrl<Schemas.MessageTemplate>
> => ({
    name: 'workflows-create-email-template',
    schema: WorkflowsCreateEmailTemplateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsCreateEmailTemplateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
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
        if (params.sensitive !== undefined) {
            body['sensitive'] = params.sensitive
        }
        const result = await context.api.request<Schemas.MessageTemplate>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/`,
            body,
        })
        const filtered = omitResponseFields(result, ['content', 'draft_content', 'created_by']) as typeof result
        return await withPostHogUrl(context, filtered, `/workflows/library/templates/${filtered.id}`)
    },
})

const WorkflowsGetEmailTemplateSchema = () => {
    const MessagingTemplatesRetrieveParams = orvalSchemas.MessagingTemplatesRetrieveParams()
    return MessagingTemplatesRetrieveParams.omit({ project_id: true })
}

const workflowsGetEmailTemplate = (): ToolBase<
    ReturnType<typeof WorkflowsGetEmailTemplateSchema>,
    WithPostHogUrl<Schemas.MessageTemplate>
> => ({
    name: 'workflows-get-email-template',
    schema: WorkflowsGetEmailTemplateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsGetEmailTemplateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MessageTemplate>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = omitResponseFields(result, [
            'content.email.html',
            'created_by',
            'draft_content',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/workflows/library/templates/${filtered.id}`)
    },
})

const WorkflowsListEmailTemplatesSchema = () => {
    const MessagingTemplatesListQueryParams = orvalSchemas.MessagingTemplatesListQueryParams()
    return MessagingTemplatesListQueryParams
}

const workflowsListEmailTemplates = (): ToolBase<
    ReturnType<typeof WorkflowsListEmailTemplatesSchema>,
    WithPostHogUrl<Schemas.PaginatedMessageTemplateList>
> => ({
    name: 'workflows-list-email-templates',
    schema: WorkflowsListEmailTemplatesSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsListEmailTemplatesSchema>>) => {
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
            results: (result.results ?? []).map((item: any) =>
                omitResponseFields(item, ['content', 'created_by', 'draft_content'])
            ),
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

const WorkflowsMakeEmailTemplateTransactionalSchema = () => {
    const MessagingTemplatesMakeTransactionalCreateBody = orvalSchemas.MessagingTemplatesMakeTransactionalCreateBody()
    const MessagingTemplatesMakeTransactionalCreateParams =
        orvalSchemas.MessagingTemplatesMakeTransactionalCreateParams()
    return MessagingTemplatesMakeTransactionalCreateParams.omit({ project_id: true }).extend(
        MessagingTemplatesMakeTransactionalCreateBody.shape
    )
}

const WorkflowsMakeEmailTemplateTransactionalSchemaExecute = z.strictObject({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const workflowsMakeEmailTemplateTransactionalPrepare = (): ToolBase<
    ReturnType<typeof WorkflowsMakeEmailTemplateTransactionalSchema>,
    PrepareConfirmedActionResult
> => ({
    name: 'workflows-make-email-template-transactional-prepare',
    schema: WorkflowsMakeEmailTemplateTransactionalSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof WorkflowsMakeEmailTemplateTransactionalSchema>>
    ) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeProjectId = await context.stateManager.getProjectId()
        return await prepareConfirmedAction(context, {
            args: params,
            purpose: 'workflows-make-email-template-transactional',
            actionLabel: 'make email template transactional',
            messageTemplate:
                "About to make email template '{id}' transactional. This can't be undone, and its sends will ignore marketing opt-outs. Reply 'confirm' to proceed.\n",
            codec: __runtime.codec,
            stash: __runtime.stash,
            boundScope: { projectId: String(__scopeProjectId) },
        })
    },
})

const workflowsMakeEmailTemplateTransactionalExecute = (): ToolBase<
    typeof WorkflowsMakeEmailTemplateTransactionalSchemaExecute,
    WithPostHogUrl<Schemas.MessageTemplate>
> => ({
    name: 'workflows-make-email-template-transactional-execute',
    schema: WorkflowsMakeEmailTemplateTransactionalSchemaExecute,
    handler: async (
        context: Context,
        confirmationParams: z.infer<typeof WorkflowsMakeEmailTemplateTransactionalSchemaExecute>
    ) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeProjectId = await context.stateManager.getProjectId()
        const __guard = await executeConfirmedAction<
            z.infer<ReturnType<typeof WorkflowsMakeEmailTemplateTransactionalSchema>>
        >(context, {
            incomingArgs: confirmationParams,
            purpose: 'workflows-make-email-template-transactional',
            codec: __runtime.codec,
            ledger: __runtime.ledger,
            stash: __runtime.stash,
            expectedScope: { projectId: String(__scopeProjectId) },
        })
        if (!__guard.ok) {
            return __guard.result as never
        }
        const params = __guard.verifiedArgs
        const projectId = __scopeProjectId
        const body: Record<string, unknown> = {}
        if (params.from_integration_id !== undefined) {
            body['from_integration_id'] = params.from_integration_id
        }
        const result = await context.api.request<Schemas.MessageTemplate>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/${encodeURIComponent(String(params.id))}/make_transactional/`,
            body,
        })
        const filtered = omitResponseFields(result, ['content', 'draft_content', 'created_by']) as typeof result
        return await withPostHogUrl(context, filtered, `/workflows/library/templates/${filtered.id}`)
    },
})

const WorkflowsPatchEmailTemplateSchema = () => EmailTemplateDesignPatchSchema

const workflowsPatchEmailTemplate = (): ToolBase<
    ReturnType<typeof WorkflowsPatchEmailTemplateSchema>,
    Schemas.MessageTemplate
> => ({
    name: 'workflows-patch-email-template',
    schema: WorkflowsPatchEmailTemplateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsPatchEmailTemplateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const parsedParams = WorkflowsPatchEmailTemplateSchema().parse(params)
        const { id, ...body } = parsedParams
        const result = await context.api.request<Schemas.MessageTemplate>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/${encodeURIComponent(String(id))}/design/`,
            body,
        })
        const filtered = omitResponseFields(result, ['content', 'created_by', 'draft_content']) as typeof result
        return await withPostHogUrl(context, filtered, `/workflows/library/templates/${filtered.id}`)
    },
})

const WorkflowsShowEmailTemplateSchema = () => {
    const MessagingTemplatesRetrieveParams = orvalSchemas.MessagingTemplatesRetrieveParams()
    return MessagingTemplatesRetrieveParams.omit({ project_id: true })
}

const workflowsShowEmailTemplate = (): ToolBase<
    ReturnType<typeof WorkflowsShowEmailTemplateSchema>,
    WithPostHogUrl<Schemas.MessageTemplate>
> =>
    withUiApp('email-template', {
        name: 'workflows-show-email-template',
        schema: WorkflowsShowEmailTemplateSchema(),
        handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsShowEmailTemplateSchema>>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.MessageTemplate>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/${encodeURIComponent(String(params.id))}/`,
            })
            const filtered = omitResponseFields(result, [
                'content.email.design',
                'created_by',
                'draft_content',
            ]) as typeof result
            return await withPostHogUrl(context, filtered, `/workflows/library/templates/${filtered.id}`)
        },
    })

const WorkflowsUploadEmailTemplateSchema = () => {
    const MessagingTemplatesByKeyUpdateBody = orvalSchemas.MessagingTemplatesByKeyUpdateBody()
    const MessagingTemplatesByKeyUpdateParams = orvalSchemas.MessagingTemplatesByKeyUpdateParams()
    return MessagingTemplatesByKeyUpdateParams.omit({ project_id: true }).extend(
        MessagingTemplatesByKeyUpdateBody.shape
    )
}

const workflowsUploadEmailTemplate = (): ToolBase<
    ReturnType<typeof WorkflowsUploadEmailTemplateSchema>,
    WithPostHogUrl<Schemas.UploadTemplateResponse>
> => ({
    name: 'workflows-upload-email-template',
    schema: WorkflowsUploadEmailTemplateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsUploadEmailTemplateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.subject !== undefined) {
            body['subject'] = params.subject
        }
        if (params.html !== undefined) {
            body['html'] = params.html
        }
        if (params.text !== undefined) {
            body['text'] = params.text
        }
        if (params.preheader !== undefined) {
            body['preheader'] = params.preheader
        }
        if (params.source !== undefined) {
            body['source'] = params.source
        }
        if (params.if_not_superseded !== undefined) {
            body['if_not_superseded'] = params.if_not_superseded
        }
        if (params.if_code_managed !== undefined) {
            body['if_code_managed'] = params.if_code_managed
        }
        const result = await context.api.request<Schemas.UploadTemplateResponse>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/by_key/${encodeURIComponent(String(params.key))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/workflows/library/templates/${result.id}`)
    },
})

const WorkflowsSendEmailSchema = () => {
    const MessagingSendEmailCreateBody = orvalSchemas.MessagingSendEmailCreateBody()
    return MessagingSendEmailCreateBody
}

const workflowsSendEmail = (): ToolBase<ReturnType<typeof WorkflowsSendEmailSchema>, unknown> => ({
    name: 'workflows-send-email',
    schema: WorkflowsSendEmailSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsSendEmailSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.to !== undefined) {
            body['to'] = params.to
        }
        if (params.identifiers !== undefined) {
            body['identifiers'] = params.identifiers
        }
        if (params.message_data !== undefined) {
            body['message_data'] = params.message_data
        }
        if (params.template !== undefined) {
            body['template'] = params.template
        }
        if (params.template_key !== undefined) {
            body['template_key'] = params.template_key
        }
        if (params.subject !== undefined) {
            body['subject'] = params.subject
        }
        if (params.html !== undefined) {
            body['html'] = params.html
        }
        if (params.text !== undefined) {
            body['text'] = params.text
        }
        if (params.reply_to !== undefined) {
            body['reply_to'] = params.reply_to
        }
        if (params.cc !== undefined) {
            body['cc'] = params.cc
        }
        if (params.bcc !== undefined) {
            body['bcc'] = params.bcc
        }
        if (params.headers !== undefined) {
            body['headers'] = params.headers
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.capture_engagement !== undefined) {
            body['capture_engagement'] = params.capture_engagement
        }
        if (params.from !== undefined) {
            body['from'] = params.from
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging/send/email/`,
            body,
        })
        return result
    },
})

const WorkflowsUpdateEmailTemplateSchema = () => {
    const MessagingTemplatesPartialUpdateBody = orvalSchemas.MessagingTemplatesPartialUpdateBody()
    const MessagingTemplatesPartialUpdateParams = orvalSchemas.MessagingTemplatesPartialUpdateParams()
    return MessagingTemplatesPartialUpdateParams.omit({ project_id: true }).extend(
        MessagingTemplatesPartialUpdateBody.shape
    )
}

const workflowsUpdateEmailTemplate = (): ToolBase<
    ReturnType<typeof WorkflowsUpdateEmailTemplateSchema>,
    WithPostHogUrl<Schemas.MessageTemplate>
> => ({
    name: 'workflows-update-email-template',
    schema: WorkflowsUpdateEmailTemplateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsUpdateEmailTemplateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
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
        if (params.sensitive !== undefined) {
            body['sensitive'] = params.sensitive
        }
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        const result = await context.api.request<Schemas.MessageTemplate>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        const filtered = omitResponseFields(result, ['content', 'draft_content', 'created_by']) as typeof result
        return await withPostHogUrl(context, filtered, `/workflows/library/templates/${filtered.id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'workflows-create-email-template': workflowsCreateEmailTemplate,
    'workflows-get-email-template': workflowsGetEmailTemplate,
    'workflows-list-email-templates': workflowsListEmailTemplates,
    'workflows-make-email-template-transactional-prepare': workflowsMakeEmailTemplateTransactionalPrepare,
    'workflows-make-email-template-transactional-execute': workflowsMakeEmailTemplateTransactionalExecute,
    'workflows-patch-email-template': workflowsPatchEmailTemplate,
    'workflows-show-email-template': workflowsShowEmailTemplate,
    'workflows-upload-email-template': workflowsUploadEmailTemplate,
    'workflows-send-email': workflowsSendEmail,
    'workflows-update-email-template': workflowsUpdateEmailTemplate,
}
