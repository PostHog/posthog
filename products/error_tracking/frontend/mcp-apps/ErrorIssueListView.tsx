import { type ReactElement, type ReactNode, useCallback, useState } from 'react'

import { BackButton, Badge, DataTable, type DataTableColumn, formatDate, LoadingState, Stack } from '@posthog/mosaic'

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

type ViewState = { view: 'list' } | { view: 'loading'; name: string } | { view: 'detail'; issue: ErrorIssueData }

const statusConfig: Record<string, { label: string; variant: 'success' | 'danger' | 'warning' | 'neutral' }> = {
    active: { label: 'Active', variant: 'danger' },
    resolved: { label: 'Resolved', variant: 'success' },
    archived: { label: 'Archived', variant: 'neutral' },
    pending_release: { label: 'Pending release', variant: 'warning' },
    suppressed: { label: 'Suppressed', variant: 'neutral' },
}

export function ErrorIssueListView({ data, onIssueClick }: ErrorIssueListViewProps): ReactElement {
    const [viewState, setViewState] = useState<ViewState>({ view: 'list' })

    const handleClick = useCallback(
        async (issue: ErrorIssueData) => {
            if (!onIssueClick) {
                return
            }

            setViewState({ view: 'loading', name: issue.name })
            const detail = await onIssueClick(issue).catch((error) => {
                console.error('Error loading issue detail:', error)
                return null
            })

            if (detail) {
                setViewState({ view: 'detail', issue: detail })
            } else {
                setViewState({ view: 'list' })
            }
        },
        [onIssueClick]
    )

    const handleBack = useCallback(() => setViewState({ view: 'list' }), [])

    if (viewState.view === 'loading') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label="All issues" />
                    <LoadingState label={viewState.name} />
                </Stack>
            </div>
        )
    }

    if (viewState.view === 'detail') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label="All issues" />
                    <ErrorIssueView issue={viewState.issue} />
                </Stack>
            </div>
        )
    }

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
                        {data.count ?? data.results.length} issue{(data.count ?? data.results.length) === 1 ? '' : 's'}
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
}
