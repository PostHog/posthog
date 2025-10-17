import { actions, afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { HogFlow } from './hogflows/types'
import type { workflowsLogicType } from './workflowsLogicType'

export const workflowsLogic = kea<workflowsLogicType>([
    path(['products', 'workflows', 'frontend', 'workflowsLogic']),
    actions({
        toggleWorkflowStatus: (workflow: HogFlow) => ({ workflow }),
        duplicateWorkflow: (workflow: HogFlow) => ({ workflow }),
        deleteWorkflow: (workflow: HogFlow) => ({ workflow }),
        loadWorkflows: () => ({}),
    }),
    loaders(({ values }) => ({
        workflows: [
            [] as HogFlow[],
            {
                loadWorkflows: async () => {
                    const response = await api.hogFlows.getHogFlows()
                    return response.results
                },
                toggleWorkflowStatus: async ({ workflow }) => {
                    const updatedWorkflow = await api.hogFlows.updateHogFlow(workflow.id, {
                        status: workflow.status === 'active' ? 'draft' : 'active',
                    })
                    return values.workflows.map((c) => (c.id === updatedWorkflow.id ? updatedWorkflow : c))
                },
                duplicateWorkflow: async ({ workflow }) => {
                    const duplicatedWorkflow = await api.hogFlows.createHogFlow({
                        ...workflow,
                        status: 'draft',
                        name: `${workflow.name} (copy)`,
                    })
                    return [duplicatedWorkflow, ...values.workflows]
                },
                deleteWorkflow: async ({ workflow }) => {
                    await api.hogFlows.deleteHogFlow(workflow.id)
                    return values.workflows.filter((c) => c.id !== workflow.id)
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadWorkflows()
    }),
])
