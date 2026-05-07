import type { ReactElement } from 'react'

import { DataTable, type DataTableColumn, DescriptionList, formatDate } from '@posthog/mcp-ui'
import { Badge, Card, CardContent } from '@posthog/quill'

import { ExperimentData, ExperimentVariant, getConclusion, getStatus } from './utils'

export interface ExperimentViewProps {
    experiment: ExperimentData
}

export function ExperimentView({ experiment }: ExperimentViewProps): ReactElement {
    const status = getStatus(experiment)
    const variants = experiment.parameters?.feature_flag_variants ?? []

    const variantColumns: DataTableColumn<ExperimentVariant>[] = [
        { key: 'key', header: 'Key', sortable: true },
        { key: 'name', header: 'Name' },
        {
            key: 'split_percent',
            header: 'Split %',
            align: 'right',
            render: (row) => {
                const pct = row.split_percent ?? row.rollout_percentage
                return pct != null ? `${pct}%` : '\u2014'
            },
        },
    ]

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold">{experiment.name}</span>
                        <Badge variant={status.variant}>{status.label}</Badge>
                        {experiment.type && <Badge>{experiment.type}</Badge>}
                    </div>
                    {experiment.description && (
                        <span className="text-sm text-muted-foreground">{experiment.description}</span>
                    )}
                </div>

                <Card>
                    <CardContent>
                        <DescriptionList
                            columns={2}
                            items={[
                                ...(experiment.feature_flag_key
                                    ? [{ label: 'Feature flag', value: experiment.feature_flag_key }]
                                    : []),
                                ...(experiment.start_date
                                    ? [{ label: 'Started', value: formatDate(experiment.start_date) }]
                                    : []),
                                ...(experiment.end_date
                                    ? [{ label: 'Ended', value: formatDate(experiment.end_date) }]
                                    : []),
                                ...(experiment.created_at
                                    ? [{ label: 'Created', value: formatDate(experiment.created_at) }]
                                    : []),
                            ]}
                        />
                    </CardContent>
                </Card>

                {variants.length > 0 && (
                    <Card>
                        <CardContent>
                            <div className="flex flex-col gap-2">
                                <span className="text-sm font-semibold">Variants</span>
                                <DataTable<ExperimentVariant>
                                    columns={variantColumns}
                                    data={variants}
                                    emptyMessage="No variants"
                                />
                            </div>
                        </CardContent>
                    </Card>
                )}

                {experiment.conclusion && (
                    <Card>
                        <CardContent>
                            <div className="flex flex-col gap-2">
                                <div className="flex items-center gap-2">
                                    <span className="text-sm font-semibold">Conclusion</span>
                                    <Badge variant={getConclusion(experiment).variant}>
                                        {getConclusion(experiment).label}
                                    </Badge>
                                </div>
                                {experiment.conclusion_comment && (
                                    <span className="text-sm text-muted-foreground">
                                        {experiment.conclusion_comment}
                                    </span>
                                )}
                            </div>
                        </CardContent>
                    </Card>
                )}
            </div>
        </div>
    )
}
