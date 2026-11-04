import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { HogFlowsPartialUpdateParams } from '@/generated/workflows/api'
import { withUiApp } from '@/resources/ui-apps'
import { omitResponseFields, withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'
import { hogFlowPath } from '@/tools/workflows/hogFlowLink'

const LifecycleSchema = HogFlowsPartialUpdateParams().omit({ project_id: true })

type LifecycleParams = z.infer<typeof LifecycleSchema>
type LifecycleResult = WithPostHogUrl<Schemas.HogFlow>

// Kept in sync with response.exclude on the generated workflow write tools in products/workflows/mcp/tools.yaml.
const WITHOUT_STEP_INPUTS = ['actions.*.config.inputs', 'draft.actions.*.config.inputs']

const patchStatus = async (
    context: Context,
    params: LifecycleParams,
    status: 'active' | 'draft' | 'archived'
): Promise<LifecycleResult> => {
    const projectId = await context.stateManager.getProjectId()
    const result = await context.api.request<Schemas.HogFlow>({
        method: 'PATCH',
        path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/`,
        body: { status },
    })
    const compact = omitResponseFields(result, WITHOUT_STEP_INPUTS) as Schemas.HogFlow
    return await withPostHogUrl(context, compact, hogFlowPath(compact))
}

export const workflowsEnable = (): ToolBase<typeof LifecycleSchema, LifecycleResult> =>
    withUiApp('workflow', {
        name: 'workflows-enable',
        schema: LifecycleSchema,
        handler: (context, params) => patchStatus(context, params, 'active'),
    })

export const workflowsDisable = (): ToolBase<typeof LifecycleSchema, LifecycleResult> =>
    withUiApp('workflow', {
        name: 'workflows-disable',
        schema: LifecycleSchema,
        handler: (context, params) => patchStatus(context, params, 'draft'),
    })

export const workflowsArchive = (): ToolBase<typeof LifecycleSchema, LifecycleResult> =>
    withUiApp('workflow', {
        name: 'workflows-archive',
        schema: LifecycleSchema,
        handler: (context, params) => patchStatus(context, params, 'archived'),
    })
