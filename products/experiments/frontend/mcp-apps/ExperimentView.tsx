import type { ReactElement } from 'react'

import { Badge, Card, DataTable, type DataTableColumn, DescriptionList, formatDate, Stack } from '@posthog/mosaic'

export interface ExperimentVariant {
    key: string
    name?: string
    rollout_percentage?: number
}

export interface ExperimentMetric {
    kind: string
    event?: string
    property?: string
    math?: string
}

export interface ExperimentData {
    id: number
    name: string
    type?: string
    description?: string | null
    feature_flag_key?: string
    start_date?: string | null
    end_date?: string | null
    archived?: boolean
    created_at?: string
    updated_at?: string
    parameters?: {
        feature_flag_variants?: ExperimentVariant[]
        [key: string]: unknown
    }
    metrics?: ExperimentMetric[]
    metrics_secondary?: ExperimentMetric[]
    filters?: Record<string, unknown>
    conclusion?: string | null
    conclusion_comment?: string | null
    _posthogUrl?: string
}

export interface ExperimentViewProps {
    experiment: ExperimentData
}

function getStatus(exp: ExperimentData): { label: string; variant: 'success' | 'warning' | 'neutral' | 'info' } {
    if (exp.archived) {
        return { label: 'Archived', variant: 'neutral' }
    }
    if (!exp.start_date) {
        return { label: 'Draft', variant: 'neutral' }
    }
    if (exp.end_date) {
        return { label: 'Complete', variant: 'success' }
    }
    return { label: 'Running', variant: 'info' }
}

export function ExperimentView({ experiment }: ExperimentViewProps): ReactElement {
    const status = getStatus(experiment)
    const variants = experiment.parameters?.feature_flag_variants ?? []

    const variantColumns: DataTableColumn<ExperimentVariant>[] = [
        { key: 'key', header: 'Key', sortable: true },
        { key: 'name', header: 'Name' },
        {
            key: 'rollout_percentage',
            header: 'Rollout %',
            align: 'right',
            render: (row) => (row.rollout_percentage != null ? `${row.rollout_percentage}%` : '\u2014'),
        },
    ]

    return (
        <div className="p-4">
            <Stack gap="md">
                <Stack gap="xs">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold text-text-primary">{experiment.name}</span>
                        <Badge variant={status.variant} size="md">
                            {status.label}
                        </Badge>
                        {experiment.type && (
                            <Badge variant="neutral" size="sm">
                                {experiment.type}
                            </Badge>
                        )}
                    </div>
                    {experiment.description && (
                        <span className="text-sm text-text-secondary">{experiment.description}</span>
                    )}
                </Stack>

                <Card padding="md">
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
                </Card>

                {variants.length > 0 && (
                    <Card padding="md">
                        <Stack gap="sm">
                            <span className="text-sm font-semibold text-text-primary">Variants</span>
                            <DataTable<ExperimentVariant>
                                columns={variantColumns}
                                data={variants}
                                emptyMessage="No variants"
                            />
                        </Stack>
                    </Card>
                )}

                {experiment.conclusion && (
                    <Card padding="md">
                        <Stack gap="sm">
                            <div className="flex items-center gap-2">
                                <span className="text-sm font-semibold text-text-primary">Conclusion</span>
                                <Badge variant="success" size="sm">
                                    {experiment.conclusion}
                                </Badge>
                            </div>
                            {experiment.conclusion_comment && (
                                <span className="text-sm text-text-secondary">{experiment.conclusion_comment}</span>
                            )}
                        </Stack>
                    </Card>
                )}
            </Stack>
        </div>
    )
}
