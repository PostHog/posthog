// AUTO-GENERATED from products/wizard/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/wizard/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WizardInstallStartSchema = () => {
    const WizardInstallsCreateBody = orvalSchemas.WizardInstallsCreateBody()
    return WizardInstallsCreateBody
}

const wizardInstallStart = (): ToolBase<ReturnType<typeof WizardInstallStartSchema>, Schemas.WizardInstallStart> => ({
    name: 'wizard-install-start',
    schema: WizardInstallStartSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WizardInstallStartSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.repository !== undefined) {
            body['repository'] = params.repository
        }
        if (params.branch !== undefined) {
            body['branch'] = params.branch
        }
        if (params.idempotency_key !== undefined) {
            body['idempotency_key'] = params.idempotency_key
        }
        const result = await context.api.request<Schemas.WizardInstallStart>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/wizard/installs/`,
            body,
        })
        return result
    },
})

const WizardInstallStatusSchema = () => {
    const WizardInstallsRetrieveParams = orvalSchemas.WizardInstallsRetrieveParams()
    return WizardInstallsRetrieveParams.omit({ project_id: true }).extend({
        run_id: WizardInstallsRetrieveParams.shape['run_id'].describe('The run_id returned by wizard-install-start.'),
    })
}

const wizardInstallStatus = (): ToolBase<
    ReturnType<typeof WizardInstallStatusSchema>,
    Schemas.WizardInstallStatus
> => ({
    name: 'wizard-install-status',
    schema: WizardInstallStatusSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WizardInstallStatusSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WizardInstallStatus>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/wizard/installs/${encodeURIComponent(String(params.run_id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'wizard-install-start': wizardInstallStart,
    'wizard-install-status': wizardInstallStatus,
}
