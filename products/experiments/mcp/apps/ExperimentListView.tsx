import { type ReactElement, type ReactNode } from 'react'

import { Badge, DataTable, type DataTableColumn, formatDate, ListDetailView, Stack } from '@posthog/mosaic'

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
                        key: 'status' as keyof ExperimentData,
                        header: 'Status',
                        render: (row): ReactNode => {
                            const s = getStatus(row)
                            return (
                                <Badge variant={s.variant} size="sm">
                                    {s.label}
                                </Badge>
                            )
                        },
                    },
                    {
                        key: 'feature_flag_key',
                        header: 'Flag key',
                        sortable: true,
                        render: (row): ReactNode =>
                            row.feature_flag_key ? (
                                <span className="text-text-secondary">{row.feature_flag_key}</span>
                            ) : (
                                <span className="text-text-secondary">&mdash;</span>
                            ),
                    },
                    {
                        key: 'parameters' as keyof ExperimentData,
                        header: 'Variants',
                        render: (row): ReactNode => {
                            const variants = row.parameters?.feature_flag_variants
                            if (!variants || variants.length === 0) {
                                return <span className="text-text-secondary">&mdash;</span>
                            }
                            return (
                                <div className="flex gap-1 flex-wrap">
                                    {variants.map((v) => (
                                        <Badge key={v.key} variant={v.key === 'control' ? 'neutral' : 'info'} size="sm">
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
                                <span className="text-text-secondary">{formatDate(row.start_date)}</span>
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
                                    {data.results.length} experiment
                                    {data.results.length === 1 ? '' : 's'}
                                </span>
                            </div>
                            <DataTable<ExperimentData>
                                columns={columns}
                                data={data.results}
                                pageSize={10}
                                defaultSort={{ key: 'name', direction: 'asc' }}
                                emptyMessage="No experiments found"
                            />
                        </Stack>
                    </div>
                )
            }}
        />
    )
}
