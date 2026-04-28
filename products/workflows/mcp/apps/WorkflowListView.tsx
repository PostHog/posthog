import { type ReactElement, type ReactNode } from 'react'

import { Badge, DataTable, type DataTableColumn, formatDate, ListDetailView, Stack } from '@posthog/mosaic'

import { STATUS_VARIANTS } from './utils'
import { WorkflowView, type WorkflowData } from './WorkflowView'

export interface WorkflowListData {
    count?: number
    results: WorkflowData[]
    _posthogUrl?: string
}

export interface WorkflowListViewProps {
    data: WorkflowListData
    onWorkflowClick?: (workflow: WorkflowData) => Promise<WorkflowData | null>
}

export function WorkflowListView({ data, onWorkflowClick }: WorkflowListViewProps): ReactElement {
    return (
        <ListDetailView<WorkflowData>
            onItemClick={onWorkflowClick}
            backLabel="All workflows"
            getItemName={(workflow) => workflow.name}
            renderDetail={(workflow) => <WorkflowView workflow={workflow} />}
            renderList={(handleClick) => {
                const columns: DataTableColumn<WorkflowData>[] = [
                    {
                        key: 'name',
                        header: 'Name',
                        sortable: true,
                        render: (row): ReactNode =>
                            onWorkflowClick ? (
                                <button
                                    onClick={() => handleClick(row)}
                                    className="text-link underline decoration-border-primary hover:decoration-link cursor-pointer text-left transition-colors"
                                >
                                    {row.name}
                                </button>
                            ) : (
                                row.name
                            ),
                    },
                    {
                        key: 'status',
                        header: 'Status',
                        render: (row): ReactNode => {
                            const status = row.status ?? 'draft'
                            return (
                                <Badge variant={STATUS_VARIANTS[status] ?? 'neutral'} size="sm">
                                    {status.charAt(0).toUpperCase() + status.slice(1)}
                                </Badge>
                            )
                        },
                    },
                    {
                        key: 'version',
                        header: 'Version',
                        align: 'right',
                        render: (row): ReactNode => (
                            <span className="text-text-secondary">
                                {row.version != null ? `v${row.version}` : '\u2014'}
                            </span>
                        ),
                    },
                    {
                        key: 'updated_at',
                        header: 'Updated',
                        sortable: true,
                        render: (row): ReactNode =>
                            row.updated_at ? (
                                <span className="text-text-secondary">{formatDate(row.updated_at)}</span>
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
                                    {data.count ?? data.results.length} workflow
                                    {(data.count ?? data.results.length) === 1 ? '' : 's'}
                                </span>
                            </div>
                            <DataTable<WorkflowData>
                                columns={columns}
                                data={data.results}
                                pageSize={10}
                                defaultSort={{ key: 'name', direction: 'asc' }}
                                emptyMessage="No workflows found"
                            />
                        </Stack>
                    </div>
                )
            }}
        />
    )
}
