import { kea, path, actions, reducers, selectors, afterMount } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Issue, IssueStatus, KanbanColumn } from './types'
import { demoIssues } from './demoData'

import type { issueTrackerLogicType } from './IssueTrackerLogicType'

export const issueTrackerLogic = kea<issueTrackerLogicType>([
    path(['products', 'issue_tracker', 'frontend', 'IssueTrackerLogic']),
    actions({
        setActiveTab: (tab: 'backlog' | 'kanban') => ({ tab }),
        moveIssue: (issueId: string, newStatus: IssueStatus, newPosition?: number) => ({
            issueId,
            newStatus,
            newPosition,
        }),
        scopeIssue: (issueId: string) => ({ issueId }),
        reorderIssues: (sourceIndex: number, destinationIndex: number, status: IssueStatus) => ({
            sourceIndex,
            destinationIndex,
            status,
        }),
        openIssueModal: (issueId: string) => ({ issueId }),
        closeIssueModal: true,
    }),
    loaders(({ values }) => ({
        issues: {
            __default: [] as Issue[],
            loadIssues: async () => {
                try {
                    const response = await api.issues.list()

                    return response.results
                } catch (error) {
                    console.error('Failed to load issues, using demo data:', error)
                    return demoIssues
                }
            },
            moveIssue: async ({ issueId, newStatus, newPosition }) => {
                // Optimistic update
                const currentIssues = [...values.issues]
                const issueIndex = currentIssues.findIndex((issue) => issue.id === issueId)
                if (issueIndex !== -1) {
                    currentIssues[issueIndex] = {
                        ...currentIssues[issueIndex],
                        status: newStatus,
                        position: newPosition ?? currentIssues[issueIndex].position,
                        updated_at: new Date().toISOString(),
                    }
                }

                // Update in background
                api.issues
                    .update(issueId, {
                        status: newStatus,
                        position: newPosition,
                    })
                    .catch(() => {
                        // If fails, reload from server
                        actions.loadIssues()
                    })

                return currentIssues
            },
            scopeIssue: async ({ issueId }) => {
                const todoIssues = values.issues.filter((issue: Issue) => issue.status === IssueStatus.TODO)
                const nextPosition = todoIssues.length

                // Optimistic update
                const currentIssues = values.issues.map((issue) =>
                    issue.id === issueId && issue.status === IssueStatus.BACKLOG
                        ? {
                              ...issue,
                              status: IssueStatus.TODO,
                              position: nextPosition,
                              updated_at: new Date().toISOString(),
                          }
                        : issue
                )

                // Update in background
                api.issues
                    .update(issueId, {
                        status: IssueStatus.TODO,
                        position: nextPosition,
                    })
                    .catch(() => {
                        actions.loadIssues()
                    })

                return currentIssues
            },
            reorderIssues: async ({ sourceIndex, destinationIndex, status }) => {
                const statusIssues = values.issues
                    .filter((issue: Issue) => issue.status === status)
                    .sort((a, b) => a.position - b.position)

                const movedIssue = statusIssues[sourceIndex]
                if (!movedIssue) {
                    return values.issues
                }

                // Optimistic update - reorder locally first
                const reorderedStatusIssues = [...statusIssues]
                reorderedStatusIssues.splice(sourceIndex, 1)
                reorderedStatusIssues.splice(destinationIndex, 0, movedIssue)

                // Update positions for all affected items
                const currentIssues = values.issues.map((issue) => {
                    if (issue.status === status) {
                        const newIndex = reorderedStatusIssues.findIndex((si) => si.id === issue.id)
                        return { ...issue, position: newIndex }
                    }
                    return issue
                })

                // Update positions in background
                const positionUpdates = reorderedStatusIssues.map((issue, index) => {
                    if (issue.position !== index) {
                        return api.issues.update(issue.id, { position: index })
                    }
                    return Promise.resolve()
                })

                Promise.all(positionUpdates).catch(() => {
                    actions.loadIssues()
                })

                return currentIssues
            },
        },
    })),
    reducers({
        activeTab: [
            'backlog' as 'backlog' | 'kanban',
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        selectedIssueId: [
            null as string | null,
            {
                openIssueModal: (_, { issueId }) => issueId,
                closeIssueModal: () => null,
            },
        ],
    }),
    selectors({
        backlogIssues: [
            (s) => [s.issues],
            (issues): Issue[] =>
                issues.filter((issue) => issue.status === IssueStatus.BACKLOG).sort((a, b) => a.position - b.position),
        ],
        kanbanColumns: [
            (s) => [s.issues],
            (issues): KanbanColumn[] => {
                const columns: KanbanColumn[] = [
                    { id: IssueStatus.BACKLOG, title: 'Backlog', issues: [] },
                    { id: IssueStatus.TODO, title: 'To Do', issues: [] },
                    { id: IssueStatus.IN_PROGRESS, title: 'In Progress', issues: [] },
                    { id: IssueStatus.TESTING, title: 'Testing', issues: [] },
                    { id: IssueStatus.DONE, title: 'Done', issues: [] },
                ]

                issues.forEach((issue) => {
                    const column = columns.find((col) => col.id === issue.status)
                    if (column) {
                        column.issues.push(issue)
                    }
                })

                columns.forEach((column) => {
                    column.issues.sort((a, b) => a.position - b.position)
                })

                return columns
            },
        ],
        selectedIssue: [
            (s) => [s.issues, s.selectedIssueId],
            (issues, selectedIssueId): Issue | null =>
                selectedIssueId ? issues.find((issue) => issue.id === selectedIssueId) || null : null,
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadIssues()
    }),
])
