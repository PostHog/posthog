import { type ReactElement, type ReactNode, useCallback, useState } from 'react'

import { BackButton, Badge, DataTable, type DataTableColumn, formatDate, LoadingState, Stack } from '@posthog/mosaic'

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

type ViewState = { view: 'list' } | { view: 'loading'; name: string } | { view: 'detail'; experiment: ExperimentData }

export function ExperimentListView({ data, onExperimentClick }: ExperimentListViewProps): ReactElement {
    const [viewState, setViewState] = useState<ViewState>({ view: 'list' })

    const handleClick = useCallback(
        async (experiment: ExperimentData) => {
            if (!onExperimentClick) {
                return
            }

            setViewState({ view: 'loading', name: experiment.name })
            const detail = await onExperimentClick(experiment).catch((error) => {
                console.error('Error loading experiment detail:', error)
                return null
            })

            if (detail) {
                setViewState({ view: 'detail', experiment: detail })
            } else {
                setViewState({ view: 'list' })
            }
        },
        [onExperimentClick]
    )

    const handleBack = useCallback(() => setViewState({ view: 'list' }), [])

    if (viewState.view === 'loading') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label="All experiments" />
                    <LoadingState label={viewState.name} />
                </Stack>
            </div>
        )
    }

    if (viewState.view === 'detail') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label="All experiments" />
                    <ExperimentView experiment={viewState.experiment} />
                </Stack>
            </div>
        )
    }

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
                                {v.rollout_percentage != null ? `: ${v.rollout_percentage}%` : ''}
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
}
