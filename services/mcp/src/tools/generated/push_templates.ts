// AUTO-GENERATED from products/workflows/mcp/push_templates.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/push_templates/api'
import { getConfirmedActionRuntime } from '@/tools/confirmed-action-registry'
import {
    executeConfirmedAction,
    prepareConfirmedAction,
    type PrepareConfirmedActionResult,
} from '@/tools/confirmed-action-runtime'
import { withPostHogUrl, omitResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WorkflowsCreatePushTemplateSchema = () => {
    const MessagingTemplatesCreateBody = orvalSchemas.MessagingTemplatesCreateBody()
    return MessagingTemplatesCreateBody.extend({
        type: MessagingTemplatesCreateBody.shape['type'].nonoptional().describe('Always push for this tool.'),
    })
}

const workflowsCreatePushTemplate = (): ToolBase<
    ReturnType<typeof WorkflowsCreatePushTemplateSchema>,
    WithPostHogUrl<Schemas.MessageTemplate>
> => ({
    name: 'workflows-create-push-template',
    schema: WorkflowsCreatePushTemplateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsCreatePushTemplateSchema>>) => {
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
        const result = await context.api.request<Schemas.MessageTemplate>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/`,
            body,
        })
        const filtered = omitResponseFields(result, ['content', 'draft_content', 'created_by']) as typeof result
        return await withPostHogUrl(context, filtered, `/transactional/push/${filtered.id}`)
    },
})

const WorkflowsMakePushTemplateTransactionalSchema = () => {
    const MessagingTemplatesMakeTransactionalCreateBody = orvalSchemas.MessagingTemplatesMakeTransactionalCreateBody()
    const MessagingTemplatesMakeTransactionalCreateParams =
        orvalSchemas.MessagingTemplatesMakeTransactionalCreateParams()
    return MessagingTemplatesMakeTransactionalCreateParams.omit({ project_id: true }).extend(
        MessagingTemplatesMakeTransactionalCreateBody.shape
    )
}

const WorkflowsMakePushTemplateTransactionalSchemaExecute = z.strictObject({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const workflowsMakePushTemplateTransactionalPrepare = (): ToolBase<
    ReturnType<typeof WorkflowsMakePushTemplateTransactionalSchema>,
    PrepareConfirmedActionResult
> => ({
    name: 'workflows-make-push-template-transactional-prepare',
    schema: WorkflowsMakePushTemplateTransactionalSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof WorkflowsMakePushTemplateTransactionalSchema>>
    ) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeProjectId = await context.stateManager.getProjectId()
        return await prepareConfirmedAction(context, {
            args: params,
            purpose: 'workflows-make-push-template-transactional',
            inputSchema: WorkflowsMakePushTemplateTransactionalSchema(),
            actionLabel: 'Make push template sendable from code',
            messageTemplate:
                "About to make push template '{id}' sendable from code. This can't be undone, and its sends will ignore marketing opt-outs. Reply 'confirm' to proceed.\n",
            codec: __runtime.codec,
            stash: __runtime.stash,
            boundScope: { projectId: String(__scopeProjectId) },
        })
    },
})

const workflowsMakePushTemplateTransactionalExecute = (): ToolBase<
    typeof WorkflowsMakePushTemplateTransactionalSchemaExecute,
    WithPostHogUrl<Schemas.MessageTemplate>
> => ({
    name: 'workflows-make-push-template-transactional-execute',
    schema: WorkflowsMakePushTemplateTransactionalSchemaExecute,
    handler: async (
        context: Context,
        confirmationParams: z.infer<typeof WorkflowsMakePushTemplateTransactionalSchemaExecute>
    ) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeProjectId = await context.stateManager.getProjectId()
        const __guard = await executeConfirmedAction<
            z.infer<ReturnType<typeof WorkflowsMakePushTemplateTransactionalSchema>>
        >(context, {
            incomingArgs: confirmationParams,
            purpose: 'workflows-make-push-template-transactional',
            inputSchema: WorkflowsMakePushTemplateTransactionalSchema(),
            codec: __runtime.codec,
            stash: __runtime.stash,
            expectedScope: { projectId: String(__scopeProjectId) },
        })
        if (!__guard.ok) {
            return __guard.result as never
        }
        const params = __guard.verifiedArgs
        const projectId = __scopeProjectId
        const result = await context.api.request<Schemas.MessageTemplate>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_templates/${encodeURIComponent(String(params.id))}/make_transactional/`,
        })
        const filtered = omitResponseFields(result, ['content', 'draft_content', 'created_by']) as typeof result
        return await withPostHogUrl(context, filtered, `/transactional/push/${filtered.id}`)
    },
})

const WorkflowsSendPushSchema = () => {
    const MessagingSendPushCreateBody = orvalSchemas.MessagingSendPushCreateBody()
    return MessagingSendPushCreateBody
}

const WorkflowsSendPushSchemaExecute = z.strictObject({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const workflowsSendPushPrepare = (): ToolBase<
    ReturnType<typeof WorkflowsSendPushSchema>,
    PrepareConfirmedActionResult
> => ({
    name: 'workflows-send-push-prepare',
    schema: WorkflowsSendPushSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsSendPushSchema>>) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeProjectId = await context.stateManager.getProjectId()
        return await prepareConfirmedAction(context, {
            args: params,
            purpose: 'workflows-send-push',
            inputSchema: WorkflowsSendPushSchema(),
            actionLabel: 'send push notification',
            messageTemplate:
                "About to send push template '{template_id}' to every device of '{distinct_id}'. Reply 'confirm' to send it.\n",
            codec: __runtime.codec,
            stash: __runtime.stash,
            boundScope: { projectId: String(__scopeProjectId) },
        })
    },
})

const workflowsSendPushExecute = (): ToolBase<typeof WorkflowsSendPushSchemaExecute, unknown> => ({
    name: 'workflows-send-push-execute',
    schema: WorkflowsSendPushSchemaExecute,
    handler: async (context: Context, confirmationParams: z.infer<typeof WorkflowsSendPushSchemaExecute>) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeProjectId = await context.stateManager.getProjectId()
        const __guard = await executeConfirmedAction<z.infer<ReturnType<typeof WorkflowsSendPushSchema>>>(context, {
            incomingArgs: confirmationParams,
            purpose: 'workflows-send-push',
            inputSchema: WorkflowsSendPushSchema(),
            codec: __runtime.codec,
            stash: __runtime.stash,
            expectedScope: { projectId: String(__scopeProjectId) },
        })
        if (!__guard.ok) {
            return __guard.result as never
        }
        const params = __guard.verifiedArgs
        const projectId = __scopeProjectId
        const body: Record<string, unknown> = {}
        if (params.template_id !== undefined) {
            body['template_id'] = params.template_id
        }
        if (params.distinct_id !== undefined) {
            body['distinct_id'] = params.distinct_id
        }
        if (params.message_data !== undefined) {
            body['message_data'] = params.message_data
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging/send/push/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'workflows-create-push-template': workflowsCreatePushTemplate,
    'workflows-make-push-template-transactional-prepare': workflowsMakePushTemplateTransactionalPrepare,
    'workflows-make-push-template-transactional-execute': workflowsMakePushTemplateTransactionalExecute,
    'workflows-send-push-prepare': workflowsSendPushPrepare,
    'workflows-send-push-execute': workflowsSendPushExecute,
}
