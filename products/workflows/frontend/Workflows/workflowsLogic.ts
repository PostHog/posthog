import FuseClass from 'fuse.js'
import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { HogFlow } from './hogflows/types'
import type { workflowsLogicType } from './workflowsLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<HogFlow> {}

export interface WorkflowsFilters {
    search: string
    createdBy: string | null
    status: string | null
}

export const workflowsLogic = kea<workflowsLogicType>([
    path(['products', 'workflows', 'frontend', 'workflowsLogic']),
    actions({
        toggleWorkflowStatus: (workflow: HogFlow) => ({ workflow }),
        duplicateWorkflow: (workflow: HogFlow) => ({ workflow }),
        deleteWorkflow: (workflow: HogFlow) => ({ workflow }),
        loadWorkflows: () => ({}),
        setFilters: (filters: Partial<WorkflowsFilters>) => ({ filters }),
        setSearchTerm: (search: string) => ({ search }),
        setCreatedBy: (createdBy: string | null) => ({ createdBy }),
        setStatus: (status: string | null) => ({ status }),
    }),
    reducers({
        filters: [
            { search: '', createdBy: null, status: null } as WorkflowsFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
                setSearchTerm: (state, { search }) => ({ ...state, search }),
                setCreatedBy: (state, { createdBy }) => ({ ...state, createdBy }),
                setStatus: (state, { status }) => ({ ...state, status }),
            },
        ],
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
    selectors({
        workflowsFuse: [
            (s) => [s.workflows],
            (workflows): Fuse => {
                return new FuseClass(workflows || [], {
                    keys: [{ name: 'name', weight: 2 }, 'description'],
                    threshold: 0.3,
                    ignoreLocation: true,
                    includeMatches: true,
                })
            },
        ],
        filteredWorkflows: [
            (s) => [s.workflows, s.filters, s.workflowsFuse],
            (workflows, filters, workflowsFuse): HogFlow[] => {
                let filtered = workflows

                // Filter by search term using Fuse
                if (filters.search) {
                    const searchResults = workflowsFuse.search(filters.search)
                    filtered = searchResults.map((result) => result.item)
                }

                // Filter by status
                if (filters.status) {
                    filtered = filtered.filter((workflow) => workflow.status === filters.status)
                }

                // Filter by creator
                if (filters.createdBy) {
                    filtered = filtered.filter((workflow) => workflow.created_by?.uuid === filters.createdBy)
                }

                return filtered
            },
        ],
        creators: [
            (s) => [s.workflows],
            (workflows) => {
                const uniqueCreators = new Map<number, { id: number; uuid: string; name: string; email: string }>()
                workflows.forEach((workflow) => {
                    if (workflow.created_by) {
                        uniqueCreators.set(workflow.created_by.id, {
                            id: workflow.created_by.id,
                            uuid: workflow.created_by.uuid,
                            name: workflow.created_by.first_name || workflow.created_by.email,
                            email: workflow.created_by.email,
                        })
                    }
                })
                return Array.from(uniqueCreators.values())
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadWorkflows()
    }),
])
