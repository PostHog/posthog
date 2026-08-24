import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconUndo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { LogMessage } from '~/queries/schema/schema-general'

import { AnomalyBandChart } from 'products/logs/frontend/components/AnomalyBandChart'
import { ServiceFilter } from 'products/logs/frontend/components/LogsViewer/Filters/ServiceFilter'
import { LogTag } from 'products/logs/frontend/components/LogTag'
import {
    BindingConstraintsEnumApi,
    type LimitedByEnumApi,
    type LogsAnomalyBaselineStageEnumApi,
    type LogsAnomalyScanIssueApi,
    type LogsAnomalyScanResponseApi,
    type LogsAnomalyScanSeriesApi,
    type LogsAnomalyVerdictEnumApi,
} from 'products/logs/frontend/generated/api.schemas'
import { SCAN_WINDOW_OPTIONS, type ScanRange, logsAnomaliesLogic } from 'products/logs/frontend/logsAnomaliesLogic'

const VERDICT_TAG: Record<LogsAnomalyVerdictEnumApi, { label: string; type: LemonTagType }> = {
    spike: { label: 'Spike', type: 'danger' },
    drop: { label: 'Drop', type: 'warning' },
    silence: { label: 'Silence', type: 'danger' },
}

const STATE_TAG: Record<LogsAnomalyScanIssueApi['state'], { label: string; type: LemonTagType }> = {
    active: { label: 'Ongoing', type: 'danger' },
    resolved: { label: 'Resolved', type: 'success' },
    // A resolved issue whose anomaly recurred near the end of the window,
    // without enough consecutive buckets to reopen yet.
    pending: { label: 'Recurring', type: 'warning' },
}

const STAGE_LABEL: Record<LogsAnomalyBaselineStageEnumApi, string> = {
    insufficient: 'Not enough history',
    cold_start: 'Cold start',
    developing: 'Developing',
    mature: 'Mature',
}

const LIMIT_LABEL: Record<LimitedByEnumApi, string> = {
    series_history: 'Limited by series history (young series, or trimmed by a retention rule)',
    team_retention: 'Limited by the project log retention setting',
    byte_budget: 'Limited by the scan read budget',
}

const CONSTRAINT_MESSAGE: Record<BindingConstraintsEnumApi, string> = {
    [BindingConstraintsEnumApi.ByteBudget]:
        'The scan degraded to stay inside its read budget, so baselines are less mature than usual.',
    [BindingConstraintsEnumApi.TeamRetention]:
        'The project log retention setting is shorter than the full lookback, so baselines are less mature than usual.',
}

const LEARNING_COLUMNS: LemonTableColumns<LogsAnomalyScanSeriesApi> = [
    {
        title: 'Severity',
        render: (_, record) => <LogTag level={record.severity as LogMessage['severity_text']} />,
    },
    {
        title: 'Baseline',
        render: (_, record) => (record.stage ? STAGE_LABEL[record.stage] : 'Not scored'),
    },
    {
        title: 'First seen',
        render: (_, record) => (record.history_start ? <TZLabel time={record.history_start} /> : '—'),
    },
    {
        title: 'Limits',
        render: (_, record) => (record.limited_by ? LIMIT_LABEL[record.limited_by] : 'Full baseline'),
    },
]

export function LogsAnomalies(): JSX.Element {
    const { serviceName, windowHours, scanResult, scanResultLoading, scanDisabledReason } =
        useValues(logsAnomaliesLogic)
    const { setServiceName, setWindowHours, runScan } = useActions(logsAnomaliesLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
                <span data-attr="logs-anomalies-service">
                    <ServiceFilter
                        value={serviceName ? [serviceName] : []}
                        onChange={(serviceNames) => setServiceName(serviceNames?.[0] ?? null)}
                        // Match the scan's baseline lookback so a service that recently went
                        // silent still shows up as a scannable suggestion.
                        dateRange={{ date_from: '-42d' }}
                        selectionMode="single"
                        emptyButtonLabel="Choose a service"
                    />
                </span>
                <LemonSelect
                    value={windowHours}
                    onChange={(value) => value !== null && setWindowHours(value)}
                    options={SCAN_WINDOW_OPTIONS}
                    data-attr="logs-anomalies-window"
                />
                <LemonButton
                    type="primary"
                    onClick={runScan}
                    loading={scanResultLoading}
                    disabledReason={scanDisabledReason}
                    data-attr="logs-anomalies-scan"
                >
                    Scan for anomalies
                </LemonButton>
            </div>

            {scanResult ? (
                <ScanResults result={scanResult} />
            ) : scanResultLoading ? null : (
                <EmptyMessage
                    title="Anomaly detection"
                    description="PostHog learns each service's normal log volume and flags spikes, drops, and silences. Choose a service and a time window, then run a scan."
                />
            )}
        </div>
    )
}

function ScanResults({ result }: { result: LogsAnomalyScanResponseApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-4" data-attr="logs-anomalies-results">
            <ConstraintsBanner result={result} />
            {result.issues.length > 0 ? (
                <div className="flex flex-col gap-2">
                    {result.issues.map((issue, index) => (
                        <IssueCard key={index} issue={issue} />
                    ))}
                </div>
            ) : (
                <LemonBanner type="success">
                    No anomalies in this window. Log volume for {result.service_name} stayed inside its expected bands
                    from <TZLabel time={result.eval_start} /> to <TZLabel time={result.eval_end} />.
                </LemonBanner>
            )}
            <BandCharts series={result.series} serviceName={result.service_name} />
            <LearningStatus series={result.series} lookbackDays={result.lookback_days} />
        </div>
    )
}

function BandCharts({
    series,
    serviceName,
}: {
    series: LogsAnomalyScanSeriesApi[]
    serviceName: string
}): JSX.Element | null {
    const { zoomedRange, scanDisabledReason } = useValues(logsAnomaliesLogic)
    const { zoomToRange, resetZoom } = useActions(logsAnomaliesLogic)
    const withBuckets = series.filter((s) => s.buckets.length > 0)
    if (withBuckets.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-2" data-attr="logs-anomalies-band-charts">
            <h3 className="mb-0">Observed vs expected</h3>
            <div className="text-secondary text-sm">
                Log volume per 5 minute bucket against the learned band. Marked points fell outside the band. Drag
                across a chart to scan a narrower window, or click a bucket to read its logs.
            </div>
            {withBuckets.map((s) => (
                <div key={s.severity} className="rounded border bg-surface-primary p-3">
                    <div className="mb-2 flex items-center gap-2">
                        <LogTag level={s.severity as LogMessage['severity_text']} />
                        <span className="text-secondary text-xs">{s.stage ? STAGE_LABEL[s.stage] : 'Not scored'}</span>
                        {/* Per chart rather than in the toolbar: you drag on a chart, so the way back
                            has to be next to the chart you dragged on. */}
                        {zoomedRange && (
                            <LemonButton
                                className="ml-auto"
                                size="xsmall"
                                type="secondary"
                                icon={<IconUndo />}
                                onClick={resetZoom}
                                disabledReason={scanDisabledReason}
                                data-attr="logs-anomalies-reset-zoom"
                            >
                                Reset zoom
                            </LemonButton>
                        )}
                    </div>
                    <AnomalyBandChart
                        buckets={s.buckets}
                        onZoom={zoomToRange}
                        onBucketClick={(range) => openLogsForBucket(serviceName, s.severity, range)}
                    />
                </div>
            ))}
        </div>
    )
}

function openLogsForBucket(serviceName: string, severity: string, range: ScanRange): void {
    router.actions.push(
        combineUrl(urls.logs(), {
            activeTab: 'viewer',
            serviceNames: serviceName,
            severityLevels: severity,
            dateRange: { date_from: range.dateFrom, date_to: range.dateTo },
        }).url
    )
}

function ConstraintsBanner({ result }: { result: LogsAnomalyScanResponseApi }): JSX.Element | null {
    if (!result.degraded && !result.eval_clipped && result.binding_constraints.length === 0) {
        return null
    }
    return (
        <LemonBanner type="warning" data-attr="logs-anomalies-constraints">
            <div className="flex flex-col gap-1">
                <span>
                    This scan used {result.lookback_days.toFixed(1)} days of baseline history
                    {result.eval_clipped ? (
                        <>
                            {' '}
                            and was clipped to the window from <TZLabel time={result.eval_start} /> to{' '}
                            <TZLabel time={result.eval_end} />
                        </>
                    ) : null}
                    .
                </span>
                {result.binding_constraints.length > 0 ? (
                    <ul className="list-disc pl-4">
                        {result.binding_constraints.map((constraint) => (
                            <li key={constraint}>{CONSTRAINT_MESSAGE[constraint]}</li>
                        ))}
                    </ul>
                ) : null}
            </div>
        </LemonBanner>
    )
}

function IssueCard({ issue }: { issue: LogsAnomalyScanIssueApi }): JSX.Element {
    const verdict = VERDICT_TAG[issue.kind]
    const state = STATE_TAG[issue.state]
    return (
        <div className="rounded border bg-surface-primary p-3 flex flex-col gap-2" data-attr="logs-anomalies-issue">
            <div className="flex items-center gap-2">
                <LemonTag type={verdict.type}>{verdict.label}</LemonTag>
                {issue.severity ? <LogTag level={issue.severity as LogMessage['severity_text']} /> : null}
                {state ? <LemonTag type={state.type}>{state.label}</LemonTag> : null}
            </div>
            <div className="text-secondary text-sm">
                Opened <TZLabel time={issue.opened_at} />
                {issue.resolved_at ? (
                    <>
                        , resolved <TZLabel time={issue.resolved_at} />
                    </>
                ) : (
                    <>
                        , last anomalous <TZLabel time={issue.last_anomalous_at} />
                    </>
                )}
                {' · '}
                {pluralize(issue.anomalous_bucket_times.length, 'anomalous bucket')}
            </div>
        </div>
    )
}

function LearningStatus({
    series,
    lookbackDays,
}: {
    series: LogsAnomalyScanSeriesApi[]
    lookbackDays: number
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <h3 className="mb-0">What the detector has learned</h3>
            <div className="text-secondary text-sm">
                Baselines built from {lookbackDays.toFixed(1)} days of history.
            </div>
            <LemonTable
                dataSource={series}
                columns={LEARNING_COLUMNS}
                rowKey="severity"
                size="small"
                emptyState="No log series found for this service in the scanned window."
                data-attr="logs-anomalies-learning"
            />
        </div>
    )
}
