import { UniqueIdentifier } from '@dnd-kit/core'
import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { demoTasks } from './demoData'
import type { tasksLogicType } from './tasksLogicType'
import { Task, TaskTrackerTab, TaskUpsertProps, TaskWorkflow, WorkflowStage } from './types'

export const tasksLogic = kea<tasksLogicType>([
    path(['products', 'tasks', 'frontend', 'tasksLogic']),
    connect(() => ({
        values: [router, ['location']],
    })),
    actions({
        setActiveTab: (tab: TaskTrackerTab) => ({ tab }),
        moveTask: (taskId: string, newStageKey: string, newPosition?: number) => ({
            taskId,
            newStageKey,
            newPosition,
        }),
        createTask: (task: TaskUpsertProps) => ({ task }),
        updateTask: (id: Task['id'], data: Partial<TaskUpsertProps>) => ({ id, data }),
        assignTaskToWorkflow: (taskId: string, workflowId: string) => ({ taskId, workflowId }),
        reorderTasks: (sourceIndex: number, destinationIndex: number, stageKey: string) => ({
            sourceIndex,
            destinationIndex,
            stageKey,
        }),
        openTaskDetail: (taskId: Task['id']) => ({ taskId }),
        openCreateModal: true,
        closeCreateModal: true,
        startPolling: true,
        stopPolling: true,
        pollForUpdates: true,
        startReordering: true,
        endReordering: true,
    }),
    loaders(({ values, actions }) => ({
        tasks: [
            [] as Task[],
            {
                loadTasks: async () => {
                    try {
                        const response = await api.tasks.list()
                        return response.results
                    } catch (error) {
                        console.error('Failed to load tasks, using demo data:', error)
                        return demoTasks
                    }
                },
                createTask: async ({ task }) => {
                    try {
                        const response = await api.tasks.create(task)
                        return [...values.tasks, response]
                    } catch (error) {
                        lemonToast.error('Failed to create task. Please try again.')
                        console.error('Failed to create task:', error)
                        throw error
                    }
                },
                updateTask: async ({ id, data }) => {
                    try {
                        const response = await api.tasks.update(id, data)
                        return [...values.tasks].map((task) => (task.id === id ? { ...task, ...response } : task))
                    } catch (error) {
                        lemonToast.error('Failed to update task. Please try again.')
                        console.error('Failed to update task:', error)
                        throw error
                    }
                },
                assignTaskToWorkflow: async ({ taskId, workflowId }) => {
                    // Find the target workflow
                    const targetWorkflow = values.allWorkflows.find((w) => w.id === workflowId)
                    if (!targetWorkflow || !targetWorkflow.stages?.length) {
                        console.error('Workflow not found or has no stages:', workflowId)
                        return values.tasks
                    }

                    // Find the input stage (first stage by position)
                    const inputStage = targetWorkflow.stages
                        .filter((s) => !s.is_archived)
                        .sort((a, b) => a.position - b.position)[0]

                    if (!inputStage) {
                        console.error('No input stage found for workflow:', workflowId)
                        return values.tasks
                    }

                    // Count tasks already in this stage for positioning
                    const stageTaskCount = values.tasks.filter(
                        (task) => task.workflow === workflowId && task.current_stage === inputStage.id
                    ).length

                    // Optimistic update
                    const updatedTasks = values.tasks.map((task) =>
                        task.id === taskId
                            ? {
                                  ...task,
                                  workflow: workflowId,
                                  current_stage: inputStage.id,
                                  position: stageTaskCount,
                                  updated_at: new Date().toISOString(),
                              }
                            : task
                    )

                    // Update in background
                    api.tasks
                        .update(taskId, {
                            workflow: workflowId,
                            current_stage: inputStage.id,
                            position: stageTaskCount,
                        })
                        .then(() => {
                            lemonToast.success(`Task assigned to ${targetWorkflow.name}`)
                            actions.setActiveTab('kanban')
                            router.actions.push('/tasks')
                            actions.loadTasks()
                        })
                        .catch(() => {
                            actions.loadTasks()
                        })

                    return updatedTasks
                },
                reorderTasks: async ({ sourceIndex, destinationIndex, stageKey }) => {
                    const stageTasks = values.tasks
                        .filter((task: Task) => {
                            // For tasks with workflow, check current_stage ID matches stage ID
                            // For tasks without workflow, they're in 'backlog'
                            if (task.workflow && task.current_stage) {
                                // Find stage by ID and check if key matches
                                const stage = values.allWorkflows
                                    .flatMap((w) => w.stages || [])
                                    .find((s) => s.id === task.current_stage)
                                return stage?.key === stageKey
                            }
                            return stageKey === 'backlog'
                        })
                        .sort((a, b) => a.position - b.position)

                    const movedTask = stageTasks[sourceIndex]
                    if (!movedTask) {
                        return values.tasks
                    }

                    // Optimistic update - reorder locally first
                    const reorderedStageTasks = [...stageTasks]
                    reorderedStageTasks.splice(sourceIndex, 1)
                    reorderedStageTasks.splice(destinationIndex, 0, movedTask)

                    // Update positions for all affected items
                    const currentTasks = values.tasks.map((task) => {
                        let taskInStage = false
                        if (task.workflow && task.current_stage) {
                            const stage = values.allWorkflows
                                .flatMap((w) => w.stages || [])
                                .find((s) => s.id === task.current_stage)
                            taskInStage = stage?.key === stageKey
                        } else {
                            taskInStage = stageKey === 'backlog'
                        }

                        if (taskInStage) {
                            const newIndex = reorderedStageTasks.findIndex((st) => st.id === task.id)
                            return { ...task, position: newIndex }
                        }
                        return task
                    })

                    // Update positions in background
                    const positionUpdates = reorderedStageTasks.map((task, index) => {
                        if (task.position !== index) {
                            return api.tasks.update(task.id, { position: index })
                        }
                        return Promise.resolve()
                    })

                    Promise.all(positionUpdates).catch(() => {
                        actions.loadTasks()
                    })

                    return currentTasks
                },
                pollForUpdates: async () => {
                    // Avoid clobbering optimistic state while reordering
                    if (values.isReordering) {
                        return values.tasks
                    }
                    try {
                        const response = await api.tasks.list()
                        return response.results
                    } catch (error) {
                        console.error('Polling failed:', error)
                        return values.tasks
                    }
                },
            },
        ],
        defaultWorkflow: [
            null as TaskWorkflow | null,
            {
                loadDefaultWorkflow: async () => {
                    try {
                        const response = await api.get('api/projects/@current/workflows/')
                        const workflows = response.results || []
                        return workflows.find((w: TaskWorkflow) => w.is_default) || null
                    } catch (error) {
                        console.error('Failed to load default workflow:', error)
                        return null
                    }
                },
            },
        ],
        allWorkflows: [
            [] as TaskWorkflow[],
            {
                loadAllWorkflows: async () => {
                    try {
                        const response = await api.get('api/projects/@current/workflows/')
                        return response.results || []
                    } catch (error) {
                        console.error('Failed to load workflows:', error)
                        return []
                    }
                },
            },
        ],
    })),
    reducers({
        activeTab: [
            'dashboard' as TaskTrackerTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        isCreateModalOpen: [
            false,
            {
                openCreateModal: () => true,
                closeCreateModal: () => false,
            },
        ],
        pollingInterval: [
            null as number | null,
            {
                startPolling: () => null, // Set in listener
                stopPolling: () => null,
            },
        ],
        isReordering: [
            false,
            {
                startReordering: () => true,
                endReordering: () => false,
            },
        ],
    }),
    selectors({
        workflowKanbanData: [
            (s) => [s.tasks, s.allWorkflows],
            (
                tasks,
                allWorkflows
            ): Array<{
                workflow: TaskWorkflow
                stages: Array<{
                    stage: WorkflowStage
                    tasks: Task[]
                }>
            }> => {
                return allWorkflows
                    .map((workflow) => {
                        // Get active stages for this workflow
                        const workflowStages = (workflow.stages || [])
                            .filter((stage) => !stage.is_archived)
                            .sort((a, b) => a.position - b.position)

                        // Create stage buckets for this workflow
                        const stageBuckets = workflowStages.map((stage) => {
                            // Find tasks for this specific stage/workflow
                            const stageTasks = tasks
                                .filter((task) => {
                                    // Task must be in this workflow and this stage
                                    return task.workflow === workflow.id && task.current_stage === stage.id
                                })
                                .sort((a, b) => a.position - b.position)

                            return {
                                stage,
                                tasks: stageTasks,
                            }
                        })

                        return {
                            workflow,
                            stages: stageBuckets,
                        }
                    })
                    .filter((workflowData) => workflowData.stages.length > 0) // Only show workflows with stages
            },
        ],

        // Keep the old kanbanColumns for backwards compatibility (can be removed later)
        kanbanColumns: [
            (s) => [s.workflowKanbanData],
            (workflowKanbanData): Record<UniqueIdentifier, Task[]> => {
                // Flatten all workflow stages into a single structure for legacy compatibility
                const buckets: Record<string, Task[]> = {}

                workflowKanbanData.forEach(({ stages }) => {
                    stages.forEach(({ stage, tasks }) => {
                        buckets[stage.key] = [...(buckets[stage.key] || []), ...tasks]
                    })
                })

                return buckets
            },
        ],

        // Backlog shows ALL tasks regardless of workflow status
        backlogTasks: [(s) => [s.tasks], (tasks): Task[] => tasks.sort((a, b) => a.position - b.position)],

        // Unassigned tasks sorted by creation time (most recent first)
        unassignedTasks: [
            (s) => [s.tasks],
            (tasks): Task[] =>
                tasks
                    .filter((task) => !task.workflow)
                    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
        ],

        // Assigned tasks sorted by creation time (most recent first)
        assignedTasks: [
            (s) => [s.tasks],
            (tasks): Task[] =>
                tasks
                    .filter((task) => task.workflow)
                    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
        ],
        workflowStages: [
            (s) => [s.allWorkflows],
            (allWorkflows): WorkflowStage[] => {
                // Collect all unique stages from all active workflows
                const allStages = new Map<string, WorkflowStage>()

                allWorkflows.forEach((workflow) => {
                    workflow.stages?.forEach((stage) => {
                        if (!stage.is_archived) {
                            allStages.set(stage.key, stage)
                        }
                    })
                })

                // Sort stages by position and return as array
                return Array.from(allStages.values()).sort((a, b) => a.position - b.position)
            },
        ],
        hasActiveTasks: [
            (s) => [s.tasks, s.allWorkflows],
            (tasks, allWorkflows): boolean =>
                tasks.some((task) => {
                    if (task.workflow && task.current_stage) {
                        const stage = allWorkflows
                            .flatMap((w) => w.stages || [])
                            .find((s) => s.id === task.current_stage)
                        // Task is active if it's in a stage with an agent assigned
                        if (stage && !stage.is_archived && stage.agent) {
                            return true
                        }
                    }
                    return false
                }),
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        setActiveTab: ({ tab }) => {
            if (tab === 'kanban') {
                actions.loadAllWorkflows()
            }
        },
        openTaskDetail: ({ taskId }) => {
            router.actions.push(`/tasks/${taskId}`)
        },
        moveTask: async ({ taskId, newStageKey, newPosition }) => {
            actions.startReordering()

            const currentTasks = [...values.tasks]
            const moved = currentTasks.find((t) => t.id === taskId)
            if (!moved) {
                actions.endReordering()
                return
            }

            // Find the workflow and stage for the target
            let targetWorkflow = null
            let targetStage = null

            for (const workflow of values.allWorkflows) {
                const stage = workflow.stages?.find((s) => s.key === newStageKey)
                if (stage) {
                    targetWorkflow = workflow
                    targetStage = stage
                    break
                }
            }

            if (!targetWorkflow || !targetStage) {
                console.error('Cannot find workflow/stage for:', newStageKey)
                actions.endReordering()
                return
            }

            // Validate that task can only move within same workflow
            if (moved.workflow && moved.workflow !== targetWorkflow.id) {
                console.error('Task cannot be moved to different workflow')
                actions.endReordering()
                return
            }

            const updatedTask = {
                ...moved,
                workflow: targetWorkflow.id,
                current_stage: targetStage.id,
                position: newPosition ?? 0,
                updated_at: new Date().toISOString(),
            }

            // Optimistically update the tasks
            const updatedTasks = currentTasks.map((t) => (t.id === taskId ? updatedTask : t))
            actions.loadTasksSuccess(updatedTasks)

            // Persist the task update to backend
            try {
                await api.update(`api/projects/@current/tasks/${taskId}/`, {
                    workflow: updatedTask.workflow,
                    current_stage: updatedTask.current_stage,
                    position: updatedTask.position,
                })
            } catch (error) {
                console.error('Failed to move task:', error)
                actions.loadTasks() // Reload on error
            }

            actions.endReordering()
        },

        startPolling: () => {
            if (cache.pollingInterval) {
                clearInterval(cache.pollingInterval)
            }
            cache.pollingInterval = setInterval(() => {
                if (values.hasActiveTasks) {
                    actions.pollForUpdates()
                } else {
                    actions.stopPolling()
                }
            }, 3000) // Poll every 3 seconds
        },
        stopPolling: () => {
            if (cache.pollingInterval) {
                clearInterval(cache.pollingInterval)
                cache.pollingInterval = null
            }
        },
        loadTasksSuccess: () => {
            // Start polling when tasks are loaded if there are active tasks
            if (values.hasActiveTasks && !cache.pollingInterval) {
                actions.startPolling()
            } else if (!values.hasActiveTasks && cache.pollingInterval) {
                actions.stopPolling()
            }
        },
        moveTaskSuccess: () => {
            // Check if polling should start/stop after moving a task
            if (values.hasActiveTasks && !cache.pollingInterval) {
                actions.startPolling()
            } else if (!values.hasActiveTasks && cache.pollingInterval) {
                actions.stopPolling()
            }
        },
        pollForUpdatesSuccess: () => {
            // Stop polling if there are no active tasks
            if (!values.hasActiveTasks) {
                actions.stopPolling()
            }
        },
    })),
    actionToUrl(({ values }) => {
        const changeUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] | void => {
            const searchParams: Record<string, string> = {}
            searchParams['tab'] = values.activeTab
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: false }]
        }

        return {
            setActiveTab: changeUrl,
        }
    }),
    urlToAction(({ actions, values }) => ({
        '/tasks': async (_, searchParams) => {
            const tabInURL = searchParams['tab'] as string | undefined
            const validTabs: TaskTrackerTab[] = ['dashboard', 'backlog', 'kanban', 'settings']

            // No tab in URL, set to dashboard
            if (!tabInURL) {
                if (values.activeTab !== 'dashboard') {
                    actions.setActiveTab('dashboard')
                }
                return
            }

            // Clean up tab from params if invalid and navigate to dashboard
            if (!validTabs.includes(tabInURL as TaskTrackerTab)) {
                actions.setActiveTab('dashboard')
                const cleanParams = { ...searchParams }
                delete cleanParams.tab
                router.actions.push(router.values.location.pathname, cleanParams)
                return
            }

            if (tabInURL !== values.activeTab) {
                actions.setActiveTab(tabInURL as TaskTrackerTab)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTasks()
        actions.loadDefaultWorkflow()
        actions.loadAllWorkflows()
    }),
    beforeUnmount(({ cache }) => {
        if (cache.pollingInterval) {
            clearInterval(cache.pollingInterval)
        }
    }),
])
