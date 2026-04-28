import { type ReactElement, type ReactNode } from 'react'

import { Badge, DataTable, type DataTableColumn, formatDate, ListDetailView, Stack } from '@posthog/mosaic'

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

const statusConfig: Record<string, { label: string; variant: 'success' | 'danger' | 'warning' | 'neutral' }> = {
    active: { label: 'Active', variant: 'danger' },
    resolved: { label: 'Resolved', variant: 'success' },
    archived: { label: 'Archived', variant: 'neutral' },
    pending_release: { label: 'Pending release', variant: 'warning' },
    suppressed: { label: 'Suppressed', variant: 'neutral' },
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
                                <button
                                    onClick={() => handleClick(row)}
                                    className="text-link underline decoration-border-primary hover:decoration-link cursor-pointer text-left transition-colors max-w-xs truncate block"
                                >
                                    {row.name}
                                </button>
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
                                variant: 'neutral' as const,
                            }
                            return (
                                <Badge variant={cfg.variant} size="sm">
                                    {cfg.label}
                                </Badge>
                            )
                        },
                    },
                    {
                        key: 'first_seen',
                        header: 'First seen',
                        sortable: true,
                        render: (row): ReactNode =>
                            row.first_seen ? (
                                <span className="text-text-secondary">{formatDate(row.first_seen)}</span>
                            ) : (
                                <span className="text-text-secondary">&mdash;</span>
                            ),
                    },
                ]

                return (
                    <div className="p-4">
                        <Stack gap="sm">
                            <div className="flex items-center justify-between">
                                <span className="text-sm text-text-secondary">
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
                        </Stack>
                    </div>
                )
            }}
        />
    )
}
