import { type ReactElement, type ReactNode } from 'react'

import { Badge, DataTable, type DataTableColumn, formatDate, ListDetailView, Stack } from '@posthog/mosaic'

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

export function SurveyListView({ data, onSurveyClick }: SurveyListViewProps): ReactElement {
    return (
        <ListDetailView<SurveyData>
            onItemClick={onSurveyClick}
            backLabel="All surveys"
            getItemName={(survey) => survey.name}
            renderDetail={(survey) => <SurveyView survey={survey} />}
            renderList={(handleClick) => {
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
                        render: (row): ReactNode => (
                            <span className="text-text-secondary">{row.questions?.length ?? 0}</span>
                        ),
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
            }}
        />
    )
}
