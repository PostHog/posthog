import { type ReactElement, type ReactNode } from 'react'

import { DataTable, type DataTableColumn, ListDetailView, formatDate } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

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
                        key: 'type',
                        header: 'Type',
                        render: (row): ReactNode =>
                            row.type ? (
                                <Badge>{SURVEY_TYPE_LABELS[row.type] ?? row.type}</Badge>
                            ) : (
                                <span className="text-muted-foreground">&mdash;</span>
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
                        key: 'questions' as keyof SurveyData,
                        header: 'Questions',
                        render: (row): ReactNode => (
                            <span className="text-muted-foreground">{row.questions?.length ?? 0}</span>
                        ),
                    },
                    {
                        key: 'created_at',
                        header: 'Created',
                        sortable: true,
                        render: (row): ReactNode =>
                            row.created_at ? (
                                <span className="text-muted-foreground">{formatDate(row.created_at)}</span>
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
                        </div>
                    </div>
                )
            }}
        />
    )
}
