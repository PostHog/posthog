import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { AgentDefinition, TaskWorkflow, WorkflowStage } from '../types'
import type { workflowBuilderLogicType } from './workflowBuilderLogicType'

export interface WorkflowBuilderLogicProps {
    workflow?: TaskWorkflow
}

// Extended WorkflowStage to include agent assignment
export interface ExtendedWorkflowStage extends WorkflowStage {
    agent_id?: string
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
        updateStage: (stageId: string, updates: Partial<ExtendedWorkflowStage>) => ({ stageId, updates }),
        saveWorkflow: true,
        setSavedWorkflow: (workflow: TaskWorkflow) => ({ workflow }),
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
            (props.workflow?.stages && props.workflow.stages.length > 0) 
                ? props.workflow.stages.map(stage => ({
                    ...stage,
                    agent_id: stage.agent || ''
                  } as ExtendedWorkflowStage))
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
                        agent_id: '',
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
                        agent_id: '',
                    }
                ],
            {
                addStage: (state) => {
                    // Insert new stage before the Complete stage (at position length - 1)
                    if (!state || state.length === 0) return state
                    const newPosition = state.length - 1
                    const suggestedNames = ['Planning', 'Development', 'Review', 'Testing', 'Deployment']
                    const stageName = newPosition <= suggestedNames.length 
                        ? suggestedNames[newPosition - 1] || `Stage ${newPosition}`
                        : `Stage ${newPosition}`
                    
                    const newStage: ExtendedWorkflowStage = {
                        id: `temp-${Date.now()}`,
                        name: stageName,
                        key: stageName.toLowerCase().replace(/\s+/g, '_'),
                        position: newPosition,
                        color: '#6b7280',
                        is_manual_only: false,
                        is_archived: false,
                        task_count: 0,
                        agent_id: ''
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
    })),

    selectors({
        isValid: [
            (s) => [s.workflowName, s.stages],
            (workflowName, stages): boolean => {
                return workflowName.trim().length > 0 && 
                       stages && stages.length >= 2 && 
                       stages[stages.length - 1]?.name.toLowerCase() === 'complete'
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
                    // Update existing workflow
                    const response = await api.update(
                        `api/projects/@current/workflows/${props.workflow.id}/`,
                        workflowData
                    )
                    workflow = response
                } else {
                    // Create new workflow
                    const response = await api.create('api/projects/@current/workflows/', workflowData)
                    workflow = response
                }

                // Save stages with their agent configurations
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
                        is_manual_only: stage.name.toLowerCase() === 'complete' ? true : !stage.agent_id, // Complete stage is always manual
                        agent: stage.name.toLowerCase() === 'complete' ? null : (stage.agent_id || null)
                    }

                    let savedStage: WorkflowStage
                    if (stage.id.startsWith('temp-')) {
                        // Create new stage
                        savedStage = await api.create(
                            'api/projects/@current/workflow-stages/',
                            stageData
                        )
                    } else {
                        // Update existing stage
                        savedStage = await api.update(
                            `api/projects/@current/workflow-stages/${stage.id}/`,
                            stageData
                        )
                    }
                    savedStages.push(savedStage)
                }

                // No transitions needed - stages flow linearly based on position

                actions.setSavedWorkflow({ ...workflow, stages: savedStages })
            } catch (error) {
                console.error('Failed to save workflow:', error)
                throw error
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadAgents()
    }),
])