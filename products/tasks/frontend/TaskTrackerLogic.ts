import { actions, afterMount, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { UniqueIdentifier } from 'node_modules/@dnd-kit/core/dist'

import api from 'lib/api'

import { demoTasks } from './demoData'
import type { taskTrackerLogicType } from './taskTrackerLogicType'
import { Task, TaskStatus, TaskUpsertProps } from './types'

export const taskTrackerLogic = kea<taskTrackerLogicType>([
    path(['products', 'tasks', 'frontend', 'taskTrackerLogic']),
    actions({
        setActiveTab: (tab: 'backlog' | 'kanban' | 'settings') => ({ tab }),
        moveTask: (taskId: string, newStatus: TaskStatus, newPosition?: number) => ({
            taskId,
            newStatus,
            newPosition,
        }),
        createTask: (task: TaskUpsertProps) => ({ task }),
        updateTask: (id: Task['id'], data: Partial<TaskUpsertProps>) => ({ id, data }),
        scopeTask: (taskId: string) => ({ taskId }),
        reorderTasks: (sourceIndex: number, destinationIndex: number, status: TaskStatus) => ({
            sourceIndex,
            destinationIndex,
            status,
        }),
        openTaskModal: (taskId: Task['id']) => ({ taskId }),
        closeTaskModal: true,
        openCreateModal: true,
        closeCreateModal: true,
        startPolling: true,
        stopPolling: true,
        pollForUpdates: true,
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
                        console.error('Failed to create task:', error)
                        throw error
                    }
                },
                updateTask: async ({ id, data }) => {
                    try {
                        const response = await api.tasks.update(id, data)
                        return [...values.tasks].map((task) => (task.id === id ? { ...task, ...response } : task))
                    } catch (error) {
                        console.error('Failed to create task:', error)
                        throw error
                    }
                },
                moveTask: async ({ taskId, newStatus, newPosition }) => {
                    // Optimistic update
                    const currentTasks = [...values.tasks]
                    const taskIndex = currentTasks.findIndex((task) => task.id === taskId)
                    if (taskIndex !== -1) {
                        currentTasks[taskIndex] = {
                            ...currentTasks[taskIndex],
                            status: newStatus,
                            position: newPosition ?? currentTasks[taskIndex].position,
                            updated_at: new Date().toISOString(),
                        }
                    }

                    // Update in background
                    api.tasks
                        .update(taskId, {
                            status: newStatus,
                            position: newPosition,
                        })
                        .catch(() => {
                            // If fails, reload from server
                            actions.loadTasks()
                        })

                    return currentTasks
                },
                scopeTask: async ({ taskId }) => {
                    const todoTasks = values.tasks.filter((task: Task) => task.status === TaskStatus.TODO)
                    const nextPosition = todoTasks.length

                    // Optimistic update
                    const currentTasks = values.tasks.map((task) =>
                        task.id === taskId && task.status === TaskStatus.BACKLOG
                            ? {
                                  ...task,
                                  status: TaskStatus.TODO,
                                  position: nextPosition,
                                  updated_at: new Date().toISOString(),
                              }
                            : task
                    )

                    // Update in background
                    api.tasks
                        .update(taskId, {
                            status: TaskStatus.TODO,
                            position: nextPosition,
                        })
                        .catch(() => {
                            actions.loadTasks()
                        })

                    return currentTasks
                },
                reorderTasks: async ({ sourceIndex, destinationIndex, status }) => {
                    const statusTasks = values.tasks
                        .filter((task: Task) => task.status === status)
                        .sort((a, b) => a.position - b.position)

                    const movedTask = statusTasks[sourceIndex]
                    if (!movedTask) {
                        return values.tasks
                    }

                    // Optimistic update - reorder locally first
                    const reorderedStatusTasks = [...statusTasks]
                    reorderedStatusTasks.splice(sourceIndex, 1)
                    reorderedStatusTasks.splice(destinationIndex, 0, movedTask)

                    // Update positions for all affected items
                    const currentTasks = values.tasks.map((task) => {
                        if (task.status === status) {
                            const newIndex = reorderedStatusTasks.findIndex((st) => st.id === task.id)
                            return { ...task, position: newIndex }
                        }
                        return task
                    })

                    // Update positions in background
                    const positionUpdates = reorderedStatusTasks.map((task, index) => {
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
                    // Silent polling - just refresh tasks without loading state
                    try {
                        const response = await api.tasks.list()
                        return response.results
                    } catch (error) {
                        console.error('Polling failed:', error)
                        return values.tasks // Return current state on error
                    }
                },
            },
        ],
    })),
    reducers({
        activeTab: [
            'backlog' as 'backlog' | 'kanban' | 'settings',
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        selectedTaskId: [
            null as string | null,
            {
                openTaskModal: (_, { taskId }) => taskId,
                closeTaskModal: () => null,
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
    }),
    selectors({
        backlogTasks: [
            (s) => [s.tasks],
            (tasks): Task[] =>
                tasks.filter((task) => task.status === TaskStatus.BACKLOG).sort((a, b) => a.position - b.position),
        ],
        kanbanColumns: [
            (s) => [s.tasks],
            (tasks): Record<UniqueIdentifier, Task[]> => {
                return tasks.reduce(
                    (acc, task) => {
                        acc[task.status].push(task)
                        return acc
                    },
                    {
                        [TaskStatus.BACKLOG]: [],
                        [TaskStatus.TODO]: [],
                        [TaskStatus.IN_PROGRESS]: [],
                        [TaskStatus.TESTING]: [],
                        [TaskStatus.DONE]: [],
                    } as Record<TaskStatus, Task[]>
                )
            },
        ],
        selectedTask: [
            (s) => [s.tasks, s.selectedTaskId],
            (tasks, selectedTaskId): Task | null =>
                selectedTaskId ? tasks.find((task) => task.id === selectedTaskId) || null : null,
        ],
        hasActiveTasks: [
            (s) => [s.tasks],
            (tasks): boolean =>
                tasks.some(
                    (task) =>
                        task.status === TaskStatus.IN_PROGRESS ||
                        task.status === TaskStatus.TODO ||
                        task.status === TaskStatus.TESTING
                ),
        ],
    }),
    listeners(({ actions, values, cache }) => ({
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
    afterMount(({ actions }) => {
        actions.loadTasks()
    }),
    beforeUnmount(({ cache }) => {
        if (cache.pollingInterval) {
            clearInterval(cache.pollingInterval)
        }
    }),
])
