import { kea, path, actions, reducers, selectors } from 'kea'
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
        issues: [
            demoIssues as Issue[],
            {
                moveIssue: (state, { issueId, newStatus, newPosition }) => {
                    const updatedIssues = state.map((issue) =>
                        issue.id === issueId
                            ? {
                                  ...issue,
                                  status: newStatus,
                                  position: newPosition ?? issue.position,
                                  updatedAt: new Date().toISOString(),
                              }
                            : issue
                    )

                    // Reorder positions within the new status column
                    if (newPosition !== undefined) {
                        const statusIssues = updatedIssues.filter((issue) => issue.status === newStatus)
                        statusIssues.forEach((issue, index) => {
                            if (issue.id !== issueId) {
                                const targetIssue = updatedIssues.find((u) => u.id === issue.id)
                                if (targetIssue) {
                                    targetIssue.position = index >= newPosition ? index + 1 : index
                                }
                            }
                        })
                    }

                    return updatedIssues
                },
                scopeIssue: (state, { issueId }) => {
                    const todoIssues = state.filter((issue) => issue.status === IssueStatus.TODO)
                    const nextPosition = todoIssues.length

                    return state.map((issue) =>
                        issue.id === issueId && issue.status === IssueStatus.BACKLOG
                            ? {
                                  ...issue,
                                  status: IssueStatus.TODO,
                                  position: nextPosition,
                                  updatedAt: new Date().toISOString(),
                              }
                            : issue
                    )
                },
                reorderIssues: (state, { sourceIndex, destinationIndex, status }) => {
                    const statusIssues = state
                        .filter((issue) => issue.status === status)
                        .sort((a, b) => a.position - b.position)
                    const [movedIssue] = statusIssues.splice(sourceIndex, 1)
                    statusIssues.splice(destinationIndex, 0, movedIssue)

                    // Update positions
                    const updatedIssues = state.map((issue) => {
                        if (issue.status === status) {
                            const newIndex = statusIssues.findIndex((si) => si.id === issue.id)
                            return { ...issue, position: newIndex }
                        }
                        return issue
                    })

                    return updatedIssues
                },
            },
        ],
    }),
    selectors({
        backlogIssues: [
            (s) => [s.issues],
            (issues): Issue[] =>
                issues.filter((issue) => issue.status === IssueStatus.BACKLOG).sort((a, b) => a.priority - b.priority),
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
])
