import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { tasksLogic } from '../tasksLogic'
import { AgentDefinition, TaskWorkflow, WorkflowStage } from '../types'
import type { workflowBuilderLogicType } from './workflowBuilderLogicType'

export interface WorkflowBuilderLogicProps {
    workflow?: TaskWorkflow
}

const DEFAULT_WORKFLOW_COLORS = [
    '#3b82f6', // blue
    '#10b981', // emerald
    '#f59e0b', // amber
    '#ef4444', // red
    '#8b5cf6', // violet
    '#06b6d4', // cyan
    '#f97316', // orange
    '#84cc16', // lime
]

export const workflowBuilderLogic = kea<workflowBuilderLogicType>([
    path(['products', 'tasks', 'components', 'workflowBuilderLogic']),
    props({} as WorkflowBuilderLogicProps),

    actions({
        setWorkflowName: (name: string) => ({ name }),
        setWorkflowDescription: (description: string) => ({ description }),
        setWorkflowColor: (color: string) => ({ color }),
        addStage: true,
        removeStage: (stageId: string) => ({ stageId }),
        updateStage: (stageId: string, updates: Partial<WorkflowStage>) => ({ stageId, updates }),
        saveWorkflow: true,
        deleteWorkflow: true,
        setSavedWorkflow: (workflow: TaskWorkflow) => ({ workflow }),
        setDeletedWorkflow: true,
        resetBuilder: true,
    }),

    loaders({
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

    reducers(({ props }) => ({
        workflowName: [
            props.workflow?.name || '',
            {
                setWorkflowName: (_, { name }) => name,
                resetBuilder: () => '',
            },
        ],
        workflowDescription: [
            props.workflow?.description || '',
            {
                setWorkflowDescription: (_, { description }) => description,
                resetBuilder: () => '',
            },
        ],
        workflowColor: [
            props.workflow?.color || DEFAULT_WORKFLOW_COLORS[0],
            {
                setWorkflowColor: (_, { color }) => color,
                resetBuilder: () => DEFAULT_WORKFLOW_COLORS[0],
            },
        ],
        stages: [
            props.workflow?.stages && props.workflow.stages.length > 0
                ? props.workflow.stages
                : [
                      // Default stages for new workflows
                      {
                          id: 'temp-input',
                          name: 'Input',
                          key: 'input',
                          position: 0,
                          color: '#6b7280',
                          is_manual_only: true,
                          is_archived: false,
                          task_count: 0,
                      },
                      {
                          id: 'temp-complete',
                          name: 'Complete',
                          key: 'complete',
                          position: 1,
                          color: '#10b981',
                          is_manual_only: true,
                          is_archived: false,
                          task_count: 0,
                      },
                  ],
            {
                addStage: (state) => {
                    // Insert new stage before the Complete stage (at position length - 1)
                    if (!state || state.length === 0) {
                        return state
                    }
                    const newPosition = state.length - 1
                    const suggestedNames = ['Planning', 'Development', 'Review', 'Testing', 'Deployment']
                    const stageName =
                        newPosition <= suggestedNames.length
                            ? suggestedNames[newPosition - 1] || `Stage ${newPosition}`
                            : `Stage ${newPosition}`

                    const newStage: WorkflowStage = {
                        id: `temp-${Date.now()}`,
                        name: stageName,
                        key: stageName.toLowerCase().replace(/\s+/g, '_'),
                        position: newPosition,
                        color: '#6b7280',
                        is_manual_only: false,
                        is_archived: false,
                        task_count: 0,
                        agent_name: '',
                    }

                    // Insert before Complete and update positions
                    const newState = [...state]
                    newState.splice(newPosition, 0, newStage)
                    return newState.map((stage, index) => ({ ...stage, position: index }))
                },
                removeStage: (state, { stageId }) => {
                    const filtered = state.filter((s) => s.id !== stageId)
                    return filtered.map((stage, index) => ({ ...stage, position: index }))
                },
                updateStage: (state, { stageId, updates }) => {
                    return state.map((stage) => {
                        if (stage.id === stageId) {
                            const updatedStage = { ...stage, ...updates }
                            // Update key when name changes
                            if (updates.name) {
                                updatedStage.key = updates.name.toLowerCase().replace(/\s+/g, '_')
                            }
                            return updatedStage
                        }
                        return stage
                    })
                },
                resetBuilder: () => [],
            },
        ],

        savedWorkflow: [
            null as TaskWorkflow | null,
            {
                setSavedWorkflow: (_, { workflow }) => workflow,
                resetBuilder: () => null,
            },
        ],

        deletedWorkflow: [
            false,
            {
                setDeletedWorkflow: () => true,
                resetBuilder: () => false,
            },
        ],
    })),

    selectors({
        isValid: [
            (s) => [s.workflowName, s.stages],
            (workflowName, stages): boolean => {
                return (
                    workflowName.trim().length > 0 &&
                    stages &&
                    stages.length >= 2 &&
                    stages[stages.length - 1]?.name.toLowerCase() === 'complete'
                )
            },
        ],

        workflowData: [
            (s) => [s.workflowName, s.workflowDescription, s.workflowColor, s.stages],
            (workflowName, workflowDescription, workflowColor, stages) => ({
                name: workflowName,
                description: workflowDescription,
                color: workflowColor,
                stages: stages,
                is_default: false,
            }),
        ],
    }),

    listeners(({ actions, values, props }) => ({
        saveWorkflow: async () => {
            if (!values.isValid) {
                throw new Error('Workflow is not valid')
            }

            const workflowData = {
                name: values.workflowName,
                description: values.workflowDescription,
                color: values.workflowColor,
                is_default: false,
            }

            try {
                let workflow: TaskWorkflow

                if (props.workflow) {
                    const response = await api.update(
                        `api/projects/@current/workflows/${props.workflow.id}/`,
                        workflowData
                    )
                    workflow = response
                } else {
                    const response = await api.create('api/projects/@current/workflows/', workflowData)
                    workflow = response
                }

                const savedStages: WorkflowStage[] = []
                if (!values.stages || values.stages.length === 0) {
                    throw new Error('No stages to save')
                }
                for (const stage of values.stages) {
                    const stageData = {
                        workflow: workflow.id,
                        name: stage.name,
                        key: stage.key,
                        position: stage.position,
                        color: stage.color,
                        is_manual_only: stage.name.toLowerCase() === 'complete' ? true : !stage.agent_name, // Complete stage is always manual
                        agent_name: stage.name.toLowerCase() === 'complete' ? null : stage.agent_name || null,
                    }

                    let savedStage: WorkflowStage
                    if (stage.id.startsWith('temp-')) {
                        // Create new stage
                        savedStage = await api.create(
                            `api/projects/@current/workflows/${workflow.id}/stages/`,
                            stageData
                        )
                    } else {
                        // Update existing stage
                        savedStage = await api.update(
                            `api/projects/@current/workflows/${workflow.id}/stages/${stage.id}/`,
                            stageData
                        )
                    }
                    savedStages.push(savedStage)
                }

                actions.setSavedWorkflow({ ...workflow, stages: savedStages })

                lemonToast.success(props.workflow ? 'Workflow updated successfully' : 'Workflow created successfully')
                tasksLogic.actions.setActiveTab('kanban')
            } catch (error: any) {
                console.error('Failed to save workflow:', error)
                if (error?.response?.status === 400 && error?.response?.data) {
                    const errorData = error.response.data
                    if (errorData.name) {
                        lemonToast.error(errorData.name)
                    } else {
                        lemonToast.error('Failed to save workflow. Please check your input.')
                    }
                } else {
                    lemonToast.error('Failed to save workflow. Please try again.')
                }

                throw error
            }
        },

        deleteWorkflow: async () => {
            if (!props.workflow) {
                return
            }

            try {
                await api.create(`api/projects/@current/workflows/${props.workflow.id}/deactivate/`)
                actions.setDeletedWorkflow()
                lemonToast.success(
                    'Workflow deactivated successfully. Tasks have been migrated to the default workflow.'
                )
                tasksLogic.actions.setActiveTab('kanban')
                tasksLogic.actions.loadAllWorkflows()
                tasksLogic.actions.loadTasks()
            } catch (error: any) {
                console.error('Failed to deactivate workflow:', error)
                if (error?.response?.status === 400 && error?.response?.data?.error) {
                    lemonToast.error(error.response.data.error)
                } else {
                    lemonToast.error('Failed to deactivate workflow. Please try again.')
                }
                throw error
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadAgents()
    }),
])
