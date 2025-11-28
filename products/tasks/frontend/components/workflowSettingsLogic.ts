import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { AgentDefinition, TaskWorkflow } from '../types'
import type { workflowSettingsLogicType } from './workflowSettingsLogicType'

export const workflowSettingsLogic = kea<workflowSettingsLogicType>([
    path(['products', 'tasks', 'components', 'workflowSettingsLogic']),

    actions({
        selectWorkflow: (workflowId: string | null) => ({ workflowId }),
        deleteWorkflow: (workflowId: string) => ({ workflowId }),
        setDefaultWorkflow: (workflowId: string) => ({ workflowId }),
        deactivateWorkflow: (workflowId: string) => ({ workflowId }),
    }),

    loaders({
        workflows: [
            [] as TaskWorkflow[],
            {
                loadWorkflows: async () => {
                    const response = await api.get('api/projects/@current/workflows/')
                    return response.results || []
                },
            },
        ],
        agents: [
            [] as AgentDefinition[],
            {
                loadAgents: async () => {
                    const response = await api.get('api/projects/@current/agents/')
                    return response.results || []
                },
            },
        ],
    }),

    reducers({
        selectedWorkflowId: [
            null as string | null,
            {
                selectWorkflow: (_, { workflowId }) => workflowId,
            },
        ],
    }),

    selectors({
        selectedWorkflow: [
            (s) => [s.workflows, s.selectedWorkflowId],
            (workflows, selectedWorkflowId): TaskWorkflow | null => {
                if (!selectedWorkflowId) {
                    return null
                }
                return workflows.find((w) => w.id === selectedWorkflowId) || null
            },
        ],
        defaultWorkflow: [
            (s) => [s.workflows],
            (workflows): TaskWorkflow | null => {
                return workflows.find((w) => w.is_default) || null
            },
        ],
        loading: [
            (s) => [s.workflowsLoading, s.agentsLoading],
            (workflowsLoading, agentsLoading): boolean => {
                return workflowsLoading || agentsLoading
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadWorkflowsSuccess: () => {},

        deleteWorkflow: async ({ workflowId }) => {
            try {
                await api.delete(`api/projects/@current/workflows/${workflowId}/`)
                actions.loadWorkflows()
                if (values.selectedWorkflowId === workflowId) {
                    actions.selectWorkflow(null)
                }
            } catch (error) {
                console.error('Failed to delete workflow:', error)
            }
        },

        setDefaultWorkflow: async ({ workflowId }) => {
            try {
                await api.create(`api/projects/@current/workflows/${workflowId}/set_default/`, {})
                actions.loadWorkflows()
            } catch (error) {
                console.error('Failed to set default workflow:', error)
            }
        },

        deactivateWorkflow: async ({ workflowId }) => {
            try {
                await api.create(`api/projects/@current/workflows/${workflowId}/deactivate/`, {})
                actions.loadWorkflows()
                if (values.selectedWorkflowId === workflowId) {
                    actions.selectWorkflow(null)
                }
            } catch (error) {
                console.error('Failed to deactivate workflow:', error)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadWorkflows()
        actions.loadAgents()
    }),
])
