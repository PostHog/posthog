import { type ReactElement, type ReactNode, useCallback, useState } from 'react'

import { BackButton, Badge, DataTable, type DataTableColumn, formatDate, LoadingState, Stack } from '@posthog/mosaic'

import { SurveyView, type SurveyData } from './SurveyView'
import { STATUS_VARIANTS, SURVEY_TYPE_LABELS } from './utils'

export interface SurveyListData {
    results: SurveyData[]
    _posthogUrl?: string
}

export interface SurveyListViewProps {
    data: SurveyListData
    onSurveyClick?: (survey: SurveyData) => Promise<SurveyData | null>
}

type ViewState = { view: 'list' } | { view: 'loading'; name: string } | { view: 'detail'; survey: SurveyData }

export function SurveyListView({ data, onSurveyClick }: SurveyListViewProps): ReactElement {
    const [viewState, setViewState] = useState<ViewState>({ view: 'list' })

    const handleClick = useCallback(
        async (survey: SurveyData) => {
            if (!onSurveyClick) {
                return
            }

            setViewState({ view: 'loading', name: survey.name })
            const detail = await onSurveyClick(survey).catch((error) => {
                console.error('Error loading survey detail:', error)
                return null
            })

            if (detail) {
                setViewState({ view: 'detail', survey: detail })
            } else {
                setViewState({ view: 'list' })
            }
        },
        [onSurveyClick]
    )

    const handleBack = useCallback(() => setViewState({ view: 'list' }), [])

    if (viewState.view === 'loading') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label="All surveys" />
                    <LoadingState label={viewState.name} />
                </Stack>
            </div>
        )
    }

    if (viewState.view === 'detail') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label="All surveys" />
                    <SurveyView survey={viewState.survey} />
                </Stack>
            </div>
        )
    }

    const columns: DataTableColumn<SurveyData>[] = [
        {
            key: 'name',
            header: 'Name',
            sortable: true,
            render: (row): ReactNode =>
                onSurveyClick ? (
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
            key: 'type',
            header: 'Type',
            render: (row): ReactNode =>
                row.type ? (
                    <Badge variant="neutral" size="sm">
                        {SURVEY_TYPE_LABELS[row.type] ?? row.type}
                    </Badge>
                ) : (
                    <span className="text-text-secondary">&mdash;</span>
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
            key: 'questions' as keyof SurveyData,
            header: 'Questions',
            render: (row): ReactNode => <span className="text-text-secondary">{row.questions?.length ?? 0}</span>,
        },
        {
            key: 'created_at',
            header: 'Created',
            sortable: true,
            render: (row): ReactNode =>
                row.created_at ? (
                    <span className="text-text-secondary">{formatDate(row.created_at)}</span>
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
                        {data.results.length} survey{data.results.length === 1 ? '' : 's'}
                    </span>
                </div>
                <DataTable<SurveyData>
                    columns={columns}
                    data={data.results}
                    pageSize={10}
                    defaultSort={{ key: 'name', direction: 'asc' }}
                    emptyMessage="No surveys found"
                />
            </Stack>
        </div>
    )
}
