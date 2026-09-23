import { useValues } from 'kea'

import { LemonTable, LemonTag } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { MetricTypeTag } from 'scenes/experiments/MetricsView/shared/MetricTypeTag'

import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

type ListedMetric = ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery

interface MetricRow {
    key: string
    metric: ListedMetric
    isShared: boolean
}

const getSeriesLabel = (node?: { custom_name?: string; name?: string; event?: string | null }): string | undefined =>
    node?.custom_name || node?.name || node?.event || undefined

const getMetricName = (metric: ListedMetric): string => {
    if (metric.name) {
        return metric.name
    }
    if (metric.kind === NodeKind.ExperimentFunnelsQuery) {
        const series = metric.funnels_query?.series ?? []
        const firstStep = getSeriesLabel(series[0])
        const lastStep = getSeriesLabel(series[series.length - 1])
        if (series.length > 1 && firstStep && lastStep) {
            return `${firstStep} → ${lastStep}`
        }
        return firstStep || 'Untitled metric'
    }
    if (metric.kind === NodeKind.ExperimentTrendsQuery) {
        return getSeriesLabel(metric.count_query?.series?.[0]) || 'Untitled metric'
    }
    return 'Untitled metric'
}

const getMetricRows = (experiment: Experiment, type: 'primary' | 'secondary'): MetricRow[] => {
    const inlineMetrics = type === 'primary' ? experiment.metrics : experiment.metrics_secondary
    return [
        ...inlineMetrics.map((metric, index) => ({ key: metric.uuid || `inline-${index}`, metric, isShared: false })),
        ...experiment.saved_metrics
            .filter((savedMetric) => savedMetric.metadata.type === type)
            .map((savedMetric) => ({
                key: `shared-${savedMetric.saved_metric}`,
                metric: { ...savedMetric.query, name: savedMetric.name } as ListedMetric,
                isShared: true,
            })),
    ]
}

const MetricsSection = ({ title, rows }: { title: string; rows: MetricRow[] }): JSX.Element => (
    <div className="flex flex-col gap-2">
        <h2 className="font-semibold text-lg mb-0">{title}</h2>
        <LemonTable
            dataSource={rows}
            rowKey="key"
            emptyState={`No ${title.toLowerCase()}`}
            columns={[
                {
                    title: 'Metric',
                    render: (_, { metric, isShared }) => (
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="break-words">{getMetricName(metric)}</span>
                            {isShared && (
                                <LemonTag type="option" size="small">
                                    Shared
                                </LemonTag>
                            )}
                        </div>
                    ),
                },
                {
                    title: 'Type',
                    width: 0,
                    render: (_, { metric }) => <MetricTypeTag metric={metric} />,
                },
            ]}
        />
    </div>
)

export function LegacyMetricsList(): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    return (
        <div className="flex flex-col gap-6 mt-2">
            <MetricsSection title="Primary metrics" rows={getMetricRows(experiment, 'primary')} />
            <MetricsSection title="Secondary metrics" rows={getMetricRows(experiment, 'secondary')} />
        </div>
    )
}
