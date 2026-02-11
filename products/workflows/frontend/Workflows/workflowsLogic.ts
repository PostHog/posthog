import FuseClass from 'fuse.js'
import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { deleteFromTree } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'

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
        archiveWorkflow: (workflow: HogFlow) => ({ workflow }),
        restoreWorkflow: (workflow: HogFlow) => ({ workflow }),
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
    loaders(({ actions, values }) => ({
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
                archiveWorkflow: async ({ workflow }) => {
                    LemonDialog.open({
                        width: 500,
                        title: 'Archive workflow?',
                        description: `Are you sure you want to archive "${workflow.name}"?${
                            workflow.status === 'active'
                                ? ' In-progress workflow invocations will end without completing.'
                                : ''
                        }`,
                        primaryButton: {
                            children: 'Archive',
                            type: 'primary',
                            status: 'danger',
                            onClick: async () => {
                                try {
                                    await api.hogFlows.updateHogFlow(workflow.id, {
                                        status: 'archived',
                                    })
                                    lemonToast.success(`Workflow "${workflow.name}" archived`)
                                    router.actions.push(urls.workflows())
                                    actions.loadWorkflows()
                                } catch (error: any) {
                                    lemonToast.error(
                                        `Failed to archive workflow: ${error.detail || error.message || 'Unknown error'}`
                                    )
                                }
                            },
                        },
                        secondaryButton: {
                            children: 'Cancel',
                        },
                    })
                    // Return unchanged workflows since dialog handles the update
                    return values.workflows
                },
                restoreWorkflow: async ({ workflow }) => {
                    try {
                        const updatedWorkflow = await api.hogFlows.updateHogFlow(workflow.id, {
                            status: 'draft',
                        })
                        lemonToast.success(`Workflow "${workflow.name}" restored to draft status`)
                        return values.workflows.map((c) => (c.id === updatedWorkflow.id ? updatedWorkflow : c))
                    } catch (error: any) {
                        lemonToast.error(
                            `Failed to restore workflow: ${error?.detail || error?.message || 'Unknown error'}`
                        )
                        return values.workflows
                    }
                },
                deleteWorkflow: async ({ workflow }) => {
                    LemonDialog.open({
                        width: 500,
                        title: 'Delete workflow?',
                        description: `Are you sure you want to permanently delete "${workflow.name}"? This action cannot be undone.`,
                        primaryButton: {
                            children: 'Delete',
                            type: 'primary',
                            status: 'danger',
                            onClick: async () => {
                                try {
                                    await api.hogFlows.deleteHogFlow(workflow.id)
                                    lemonToast.success(`Workflow "${workflow.name}" deleted`)
                                    deleteFromTree('hog_flow/', workflow.id)
                                    actions.loadWorkflows()
                                } catch (error: any) {
                                    lemonToast.error(
                                        `Failed to delete workflow: ${error.detail || error.message || 'Unknown error'}`
                                    )
                                }
                            },
                        },
                        secondaryButton: {
                            children: 'Cancel',
                        },
                    })
                    return values.workflows
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
                let filtered = workflows.filter((workflow) => workflow.status !== 'archived')

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
        archivedWorkflows: [
            (s) => [s.workflows],
            (workflows): HogFlow[] => {
                return workflows.filter((workflow) => workflow.status === 'archived')
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
])
