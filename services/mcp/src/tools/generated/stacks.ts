// AUTO-GENERATED from products/stacks/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/stacks/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const StackDiffSchema = () => {
    const StacksDiffCreateBody = orvalSchemas.StacksDiffCreateBody()
    const StacksDiffCreateParams = orvalSchemas.StacksDiffCreateParams()
    return StacksDiffCreateParams.omit({ project_id: true })
        .extend(StacksDiffCreateBody.shape)
        .extend({
            name: StacksDiffCreateParams.shape['name'].describe(
                'The stack name from `posthog.json`, such as `web-app`.'
            ),
        })
}

const stackDiff = (): ToolBase<ReturnType<typeof StackDiffSchema>, unknown> => ({
    name: 'stack-diff',
    schema: StackDiffSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof StackDiffSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.source !== undefined) {
            body['source'] = params.source
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stacks/${encodeURIComponent(String(params.name))}/diffs/`,
            body,
        })
        return result
    },
})

const StackDiffGetSchema = () => {
    const StacksDiffRetrieveParams = orvalSchemas.StacksDiffRetrieveParams()
    return StacksDiffRetrieveParams.omit({ project_id: true }).extend({
        name: StacksDiffRetrieveParams.shape['name'].describe('The stack name the diff belongs to.'),
        diff_id: StacksDiffRetrieveParams.shape['diff_id'].describe('The `id` that `stack-diff` returned.'),
    })
}

const stackDiffGet = (): ToolBase<ReturnType<typeof StackDiffGetSchema>, Schemas.StackDiff> => ({
    name: 'stack-diff-get',
    schema: StackDiffGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof StackDiffGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.StackDiff>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stacks/${encodeURIComponent(String(params.name))}/diffs/${encodeURIComponent(String(params.diff_id))}/`,
        })
        return result
    },
})

const StackPushSchema = () => {
    const StacksDiffPushBody = orvalSchemas.StacksDiffPushBody()
    const StacksDiffPushParams = orvalSchemas.StacksDiffPushParams()
    return StacksDiffPushParams.omit({ project_id: true })
        .extend(StacksDiffPushBody.shape)
        .extend({
            name: StacksDiffPushParams.shape['name'].describe('The stack name the diff belongs to.'),
            diff_id: StacksDiffPushParams.shape['diff_id'].describe('The `id` of a ready diff from `stack-diff`.'),
        })
}

const stackPush = (): ToolBase<ReturnType<typeof StackPushSchema>, unknown> => ({
    name: 'stack-push',
    schema: StackPushSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof StackPushSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.max_removals !== undefined) {
            body['max_removals'] = params.max_removals
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stacks/${encodeURIComponent(String(params.name))}/diffs/${encodeURIComponent(String(params.diff_id))}/push/`,
            body,
        })
        return result
    },
})

const StackBindingsListSchema = () => {
    const StacksBindingsListParams = orvalSchemas.StacksBindingsListParams()
    return StacksBindingsListParams.omit({ project_id: true }).extend({
        name: StacksBindingsListParams.shape['name'].describe('The stack name from `posthog.json`.'),
    })
}

const stackBindingsList = (): ToolBase<
    ReturnType<typeof StackBindingsListSchema>,
    WithPostHogUrl<Schemas.PaginatedBindingList>
> => ({
    name: 'stack-bindings-list',
    schema: StackBindingsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof StackBindingsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedBindingList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stacks/${encodeURIComponent(String(params.name))}/bindings/`,
        })
        return await withPostHogUrl(context, result, '/stacks')
    },
})

const StackBindingLookupSchema = () => {
    const StacksBindingLookupQueryParams = orvalSchemas.StacksBindingLookupQueryParams()
    return StacksBindingLookupQueryParams
}

const stackBindingLookup = (): ToolBase<ReturnType<typeof StackBindingLookupSchema>, Schemas.BindingLookup> => ({
    name: 'stack-binding-lookup',
    schema: StackBindingLookupSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof StackBindingLookupSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.BindingLookup>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stacks/bindings/`,
            query: {
                entity_id: params.entity_id,
                kind: params.kind,
            },
        })
        return result
    },
})

const StackManagedKindsListSchema = () => z.object({})

const stackManagedKindsList = (): ToolBase<
    ReturnType<typeof StackManagedKindsListSchema>,
    Schemas.ManagedKindList
> => ({
    name: 'stack-managed-kinds-list',
    schema: StackManagedKindsListSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof StackManagedKindsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ManagedKindList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stacks/managed_kinds/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'stack-diff': stackDiff,
    'stack-diff-get': stackDiffGet,
    'stack-push': stackPush,
    'stack-bindings-list': stackBindingsList,
    'stack-binding-lookup': stackBindingLookup,
    'stack-managed-kinds-list': stackManagedKindsList,
}
