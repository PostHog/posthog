/**
 * Hooks for the generated `experiment-update` tool. A PATCH replaces the whole `parameters`
 * object, so the hook reads the stored `parameters` and merges the variant detail inputs into it.
 */
import type { Schemas } from '@/api/generated'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

import { hasVariantDetails, type VariantDetailParams, withVariantDetailsInParameters } from './variantDetails'

type UpdateParams = VariantDetailParams & { id: number | string }

async function transformBody(
    context: Context,
    params: UpdateParams,
    body: Record<string, unknown>
): Promise<Record<string, unknown>> {
    if (!hasVariantDetails(params)) {
        return body
    }
    // No try/catch: a failed GET must abort before the PATCH, else the PATCH drops the other keys.
    const projectId = await context.stateManager.getProjectId()
    const existing = await context.api.request<Schemas.Experiment>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/`,
    })
    return {
        ...withVariantDetailsInParameters(body, params, existing.parameters as Record<string, unknown> | null),
        version: existing.version ?? 0,
    }
}

export default { transformBody } satisfies ToolHooks<UpdateParams>
