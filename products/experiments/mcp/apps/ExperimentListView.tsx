import { type ReactElement, type ReactNode } from 'react'

import { DataTable, type DataTableColumn, ListDetailView, formatDate } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

import { ExperimentView } from './ExperimentView'
import { ExperimentData, getStatus } from './utils'

export interface ExperimentListData {
    count?: number
    results: ExperimentData[]
    _posthogUrl?: string
}

export interface ExperimentListViewProps {
    data: ExperimentListData
    onExperimentClick?: (experiment: ExperimentData) => Promise<ExperimentData | null>
}

export function ExperimentListView({ data, onExperimentClick }: ExperimentListViewProps): ReactElement {
    return (
        <ListDetailView<ExperimentData>
            onItemClick={onExperimentClick}
            backLabel="All experiments"
            getItemName={(experiment) => experiment.name}
            renderDetail={(experiment) => <ExperimentView experiment={experiment} />}
            renderList={(handleClick) => {
                const columns: DataTableColumn<ExperimentData>[] = [
                    {
                        key: 'name',
                        header: 'Name',
                        sortable: true,
                        render: (row): ReactNode =>
                            onExperimentClick ? (
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
                        key: 'status' as keyof ExperimentData,
                        header: 'Status',
                        render: (row): ReactNode => {
                            const s = getStatus(row)
                            return <Badge variant={s.variant}>{s.label}</Badge>
                        },
                    },
                    {
                        key: 'feature_flag_key',
                        header: 'Flag key',
                        sortable: true,
                        render: (row): ReactNode =>
                            row.feature_flag_key ? (
                                <span className="text-muted-foreground">{row.feature_flag_key}</span>
                            ) : (
                                <span className="text-muted-foreground">&mdash;</span>
                            ),
                    },
                    {
                        key: 'parameters' as keyof ExperimentData,
                        header: 'Variants',
                        render: (row): ReactNode => {
                            const variants = row.parameters?.feature_flag_variants
                            if (!variants || variants.length === 0) {
                                return <span className="text-muted-foreground">&mdash;</span>
                            }
                            return (
                                <div className="flex gap-1 flex-wrap">
                                    {variants.map((v) => (
                                        <Badge key={v.key} variant={v.key === 'control' ? 'default' : 'info'}>
                                            {v.key}
                                            {(v.split_percent ?? v.rollout_percentage) != null
                                                ? `: ${v.split_percent ?? v.rollout_percentage}%`
                                                : ''}
                                        </Badge>
                                    ))}
                                </div>
                            )
                        },
                    },
                    {
                        key: 'start_date',
                        header: 'Started',
                        sortable: true,
                        render: (row): ReactNode =>
                            row.start_date ? (
                                <span className="text-muted-foreground">{formatDate(row.start_date)}</span>
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
                                    {data.results.length} experiment{data.results.length === 1 ? '' : 's'}
                                </span>
                            </div>
                            <DataTable<ExperimentData>
                                columns={columns}
                                data={data.results}
                                pageSize={10}
                                defaultSort={{ key: 'name', direction: 'asc' }}
                                emptyMessage="No experiments found"
                            />
                        </div>
                    </div>
                )
            }}
        />
    )
}
