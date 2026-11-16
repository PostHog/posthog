import { Fragment, type ReactElement } from 'react'

import { DataTable, type DataTableColumn } from '@posthog/mcp-ui'
import { Badge, Card, CardContent, Progress } from '@posthog/quill'

export interface ExperimentVariantStats {
    key: string
    number_of_samples: number
    sum: number
    sum_squares?: number
    method?: 'bayesian' | 'frequentist'
    significant?: boolean | null
    p_value?: number | null
    confidence_interval?: number[] | null
    chance_to_win?: number | null
    credible_interval?: number[] | null
    step_counts?: number[] | null
}

export interface ExperimentMetricResult {
    baseline?: ExperimentVariantStats | null
    variant_results?: ExperimentVariantStats[] | null
}

export interface ExperimentMetricRun {
    metric_uuid: string
    status?: string
    result?: ExperimentMetricResult | null
    error_message?: string | null
}

export interface ExperimentMetricResultRow {
    index: number
    metric?: { uuid?: string | null; name?: string | null } | null
    // null when the metric query failed
    data?: ExperimentMetricResult | null
}

export interface ExperimentResultsData {
    id?: string
    experiment_id?: number
    status?: string
    total_metrics?: number
    completed_metrics?: number
    failed_metrics?: number
    created_at?: string | null
    query_to?: string | null
    completed_at?: string | null
    result_source?: string
    active_run?: { id?: string } | null
    results?: ExperimentMetricRun[]
    // The fields below come from the handwritten experiment-results-get tool
    // (services/mcp/src/tools/experiments/getResults.ts), which shares this app with
    // experiment-metrics-recalculation-latest-retrieve.
    experiment?: { id: number; name?: string }
    metrics?: {
        primary?: { results?: ExperimentMetricResultRow[] }
        secondary?: { results?: ExperimentMetricResultRow[] }
    }
    _posthogUrl?: string
}

export interface ExperimentResultsViewProps {
    data: ExperimentResultsData
}

interface VariantRow {
    variant: string
    isBaseline: boolean
    exposures: number
    perUser: number | null
    lift: number | null
    stats: ExperimentVariantStats | null
}

function formatCount(value: number): string {
    return value.toLocaleString('en-US')
}

function formatPerUser(value: number, isFunnel: boolean): string {
    if (isFunnel) {
        return `${(value * 100).toFixed(2)}%`
    }
    if (Math.abs(value) >= 100) {
        return value.toFixed(0)
    }
    return value.toFixed(2)
}

function formatLift(value: number): string {
    const pct = value * 100
    return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`
}

function formatDateTime(value: string): string {
    const date = new Date(value)
    if (isNaN(date.getTime())) {
        return value
    }
    return date.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
}

function ChanceToWinBar({ value }: { value: number }): ReactElement {
    const pct = Math.max(0, Math.min(100, value * 100))
    const variant: 'success' | 'default' | 'warning' = value > 0.95 ? 'success' : value > 0.5 ? 'default' : 'warning'
    return (
        <div className="flex items-center gap-2 justify-end">
            <Progress value={pct} variant={variant} className="w-12" />
            <span className="tabular-nums">{pct.toFixed(0)}% to win</span>
        </div>
    )
}

function significanceCell(row: VariantRow): ReactElement | string {
    if (row.isBaseline || !row.stats) {
        return '—'
    }
    const stats = row.stats
    const parts: ReactElement[] = []
    if (stats.method === 'bayesian' && stats.chance_to_win != null) {
        parts.push(<ChanceToWinBar key="ctw" value={stats.chance_to_win} />)
        if (stats.significant) {
            parts.push(
                <Badge key="sig" variant="success">
                    Significant
                </Badge>
            )
        }
    } else {
        if (stats.p_value != null) {
            parts.push(
                <span key="p" className="tabular-nums">
                    {stats.p_value < 0.001 ? 'p < 0.001' : `p = ${stats.p_value.toFixed(3)}`}
                </span>
            )
        }
        if (stats.significant != null) {
            parts.push(
                <Badge key="sig" variant={stats.significant ? 'success' : 'default'}>
                    {stats.significant ? 'Significant' : 'Not significant'}
                </Badge>
            )
        }
    }
    if (parts.length === 0) {
        return '—'
    }
    // The table grows to the width of its widest row and scrolls sideways past the card edge,
    // so stack the parts to keep this column narrow.
    return <div className="flex flex-col items-end gap-1">{parts}</div>
}

function buildRows(result: ExperimentMetricResult): VariantRow[] {
    const baseline = result.baseline
    const variants = result.variant_results ?? []
    const baselineMean = baseline && baseline.number_of_samples > 0 ? baseline.sum / baseline.number_of_samples : null

    const toRow = (stats: ExperimentVariantStats, isBaseline: boolean): VariantRow => {
        const perUser = stats.number_of_samples > 0 ? stats.sum / stats.number_of_samples : null
        const lift =
            !isBaseline && perUser != null && baselineMean != null && baselineMean !== 0
                ? perUser / baselineMean - 1
                : null
        return {
            variant: stats.key,
            isBaseline,
            exposures: stats.number_of_samples,
            perUser,
            lift,
            stats: isBaseline ? null : stats,
        }
    }

    const rows: VariantRow[] = []
    if (baseline) {
        rows.push(toRow(baseline, true))
    }
    for (const variant of variants) {
        rows.push(toRow(variant, false))
    }
    return rows
}

interface MetricEntry {
    key: string
    name: string
    result: ExperimentMetricResult | null
    failed: boolean
    errorMessage: string | null
}

interface MetricSection {
    label: string | null
    entries: MetricEntry[]
}

function entriesFromResultRows(rows: ExperimentMetricResultRow[]): MetricEntry[] {
    return rows.map((row) => ({
        key: String(row.index),
        name: row.metric?.name || `Metric ${row.index + 1}`,
        result: row.data ?? null,
        failed: row.data == null,
        errorMessage: null,
    }))
}

function metricSections(data: ExperimentResultsData): MetricSection[] {
    if (data.metrics) {
        const sections: MetricSection[] = [
            { label: 'Primary metrics', entries: entriesFromResultRows(data.metrics.primary?.results ?? []) },
            { label: 'Secondary metrics', entries: entriesFromResultRows(data.metrics.secondary?.results ?? []) },
        ]
        return sections.filter((section) => section.entries.length > 0)
    }
    const entries = (data.results ?? []).map((run, index) => ({
        key: run.metric_uuid,
        name: `Metric ${index + 1}`,
        result: run.result ?? null,
        failed: Boolean(run.error_message),
        errorMessage: run.error_message ?? null,
    }))
    return entries.length > 0 ? [{ label: null, entries }] : []
}

function MetricCard({ entry }: { entry: MetricEntry }): ReactElement {
    const result = entry.result
    const rows = result ? buildRows(result) : []
    const isFunnel =
        result?.baseline?.step_counts != null || (result?.variant_results ?? []).some((v) => v.step_counts != null)

    const columns: DataTableColumn<VariantRow>[] = [
        {
            key: 'variant',
            header: 'Variant',
            render: (row) => (
                <span>
                    {row.variant}
                    {row.isBaseline && <span className="text-muted-foreground"> (baseline)</span>}
                </span>
            ),
        },
        { key: 'exposures', header: 'Exposures', align: 'right', render: (row) => formatCount(row.exposures) },
        {
            key: 'perUser',
            header: isFunnel ? 'Conversion' : 'Mean',
            align: 'right',
            render: (row) => (row.perUser != null ? formatPerUser(row.perUser, isFunnel) : '—'),
        },
        {
            key: 'lift',
            header: 'Lift',
            align: 'right',
            render: (row) => (row.lift != null ? formatLift(row.lift) : '—'),
        },
        {
            key: 'stats',
            header: 'Significance',
            align: 'right',
            render: significanceCell,
        },
    ]

    return (
        <Card>
            <CardContent>
                <div className="flex flex-col gap-2">
                    <span className="text-sm font-semibold">{entry.name}</span>
                    {entry.failed ? (
                        <span className="text-sm text-muted-foreground">
                            {entry.errorMessage
                                ? `This metric failed to calculate: ${entry.errorMessage}`
                                : 'This metric failed to calculate. Recalculate the experiment to try again.'}
                        </span>
                    ) : (
                        <DataTable<VariantRow>
                            columns={columns}
                            data={rows}
                            emptyMessage="No results for this metric yet"
                        />
                    )}
                </div>
            </CardContent>
        </Card>
    )
}

export function ExperimentResultsView({ data }: ExperimentResultsViewProps): ReactElement {
    const sections = metricSections(data)
    const isPreliminary = data.result_source === 'timeseries_fallback'

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-lg font-semibold">{data.experiment?.name || 'Experiment results'}</span>
                    {isPreliminary && <Badge variant="warning">Preliminary</Badge>}
                    {data.status === 'failed' && <Badge variant="destructive">Failed</Badge>}
                </div>

                {data.query_to && (
                    <span className="text-sm text-muted-foreground">Data up to {formatDateTime(data.query_to)}</span>
                )}
                {isPreliminary && (
                    <span className="text-sm text-muted-foreground">
                        These numbers are estimated from daily timeseries data. Recalculate for exact results.
                    </span>
                )}
                {data.active_run && (
                    <span className="text-sm text-muted-foreground">
                        A new calculation is running. These numbers are from the previous run.
                    </span>
                )}

                {sections.length === 0 ? (
                    <Card>
                        <CardContent>
                            <span className="text-sm text-muted-foreground">
                                {data.metrics
                                    ? 'This experiment has no metrics. Add a metric to see results.'
                                    : 'No results yet. Recalculate, or wait for the experiment to collect more data.'}
                            </span>
                        </CardContent>
                    </Card>
                ) : (
                    sections.map((section) => (
                        <Fragment key={section.label ?? 'metrics'}>
                            {section.label && (
                                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                                    {section.label}
                                </span>
                            )}
                            {section.entries.map((entry) => (
                                <MetricCard key={entry.key} entry={entry} />
                            ))}
                        </Fragment>
                    ))
                )}
            </div>
        </div>
    )
}
