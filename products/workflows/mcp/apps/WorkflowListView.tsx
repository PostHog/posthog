import { type ReactElement, type ReactNode } from 'react'

import { DataTable, type DataTableColumn, ListDetailView, formatDate } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

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
                                <Button
                                    variant="link"
                                    size="sm"
                                    onClick={() => handleClick(row)}
                                    className="h-auto px-0 text-left"
                                >
                                    {row.name}
                                </Button>
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
                                <Badge variant={STATUS_VARIANTS[status] ?? 'default'}>
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
                            <span className="text-muted-foreground">
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
                                <span className="text-muted-foreground">{formatDate(row.updated_at)}</span>
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
                        </div>
                    </div>
                )
            }}
        />
    )
}
