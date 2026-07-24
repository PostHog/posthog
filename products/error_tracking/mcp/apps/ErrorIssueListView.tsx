import { type ReactElement, type ReactNode } from 'react'

import { DataTable, type DataTableColumn, ListDetailView, formatDate } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

import { ErrorIssueView, type ErrorIssueData } from './ErrorIssueView'

export interface ErrorIssueListData {
    count?: number
    results: ErrorIssueData[]
    _posthogUrl?: string
}

export interface ErrorIssueListViewProps {
    data: ErrorIssueListData
    onIssueClick?: (issue: ErrorIssueData) => Promise<ErrorIssueData | null>
}

const statusConfig: Record<string, { label: string; variant: 'success' | 'destructive' | 'warning' | 'default' }> = {
    active: { label: 'Active', variant: 'destructive' },
    resolved: { label: 'Resolved', variant: 'success' },
    archived: { label: 'Archived', variant: 'default' },
    pending_release: { label: 'Pending release', variant: 'warning' },
    suppressed: { label: 'Suppressed', variant: 'default' },
}

export function ErrorIssueListView({ data, onIssueClick }: ErrorIssueListViewProps): ReactElement {
    return (
        <ListDetailView<ErrorIssueData>
            onItemClick={onIssueClick}
            backLabel="All issues"
            getItemName={(issue) => issue.name}
            renderDetail={(issue) => <ErrorIssueView issue={issue} />}
            renderList={(handleClick) => {
                const columns: DataTableColumn<ErrorIssueData>[] = [
                    {
                        key: 'name',
                        header: 'Name',
                        sortable: true,
                        render: (row): ReactNode =>
                            onIssueClick ? (
                                <Button
                                    variant="link"
                                    size="sm"
                                    onClick={() => handleClick(row)}
                                    className="h-auto px-0 text-left max-w-xs truncate"
                                >
                                    {row.name}
                                </Button>
                            ) : (
                                <span className="max-w-xs truncate block">{row.name}</span>
                            ),
                    },
                    {
                        key: 'status',
                        header: 'Status',
                        render: (row): ReactNode => {
                            const cfg = statusConfig[row.status ?? 'active'] ?? {
                                label: row.status ?? 'Unknown',
                                variant: 'default' as const,
                            }
                            return <Badge variant={cfg.variant}>{cfg.label}</Badge>
                        },
                    },
                    {
                        key: 'first_seen',
                        header: 'First seen',
                        sortable: true,
                        render: (row): ReactNode =>
                            row.first_seen ? (
                                <span className="text-muted-foreground">{formatDate(row.first_seen)}</span>
                            ) : (
                                <span className="text-muted-foreground">&mdash;</span>
                            ),
                    },
                ]

                return (
                    <div className="p-4">
                        <div className="flex flex-col gap-2">
                            <div className="flex items-center justify-between">
                                <span className="text-sm text-muted-foreground">
                                    {data.count ?? data.results.length} issue
                                    {(data.count ?? data.results.length) === 1 ? '' : 's'}
                                </span>
                            </div>
                            <DataTable<ErrorIssueData>
                                columns={columns}
                                data={data.results}
                                pageSize={10}
                                defaultSort={{ key: 'name', direction: 'asc' }}
                                emptyMessage="No error tracking issues found"
                            />
                        </div>
                    </div>
                )
            }}
        />
    )
}
