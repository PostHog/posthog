import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInputSelect, LemonSelect, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type {
    LimitedByEnumApi,
    LogsAnomalyScanIssueApi,
    LogsAnomalyScanResponseApi,
    LogsAnomalyScanSeriesApi,
    LogsAnomalyVerdictEnumApi,
} from 'products/logs/frontend/generated/api.schemas'
import { SCAN_WINDOW_OPTIONS, logsAnomaliesLogic } from 'products/logs/frontend/logsAnomaliesLogic'

const VERDICT_TAG: Record<LogsAnomalyVerdictEnumApi, { label: string; type: LemonTagType }> = {
    spike: { label: 'Spike', type: 'danger' },
    drop: { label: 'Drop', type: 'warning' },
    silence: { label: 'Silence', type: 'danger' },
}

const STAGE_LABEL: Record<string, string> = {
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

export function LogsAnomalies(): JSX.Element {
    const {
        serviceName,
        windowHours,
        serviceSuggestions,
        serviceSuggestionsLoading,
        scanResult,
        scanResultLoading,
        scanDisabledReason,
    } = useValues(logsAnomaliesLogic)
    const { setServiceName, setWindowHours, runScan } = useActions(logsAnomaliesLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
                <div className="min-w-60">
                    <LemonInputSelect
                        mode="single"
                        placeholder="Choose a service"
                        value={serviceName ? [serviceName] : []}
                        onChange={(value) => setServiceName(value[0] ?? null)}
                        options={serviceSuggestions.map((name) => ({ key: name, label: name }))}
                        loading={serviceSuggestionsLoading}
                        allowCustomValues
                        data-attr="logs-anomalies-service"
                    />
                </div>
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
            ) : (
                !scanResultLoading && (
                    <EmptyMessage
                        title="Anomaly detection"
                        description="PostHog learns each service's normal log volume and flags spikes, drops, and silences. Choose a service and a time window, then run a scan."
                    />
                )
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
            <LearningStatus series={result.series} />
        </div>
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
                <ul className="list-disc pl-4">
                    {result.binding_constraints.map((constraint) => (
                        <li key={constraint}>
                            {constraint === 'byte_budget'
                                ? 'The scan degraded to stay inside its read budget, so baselines are less mature than usual.'
                                : 'The project log retention setting is shorter than the full lookback, so baselines are less mature than usual.'}
                        </li>
                    ))}
                </ul>
            </div>
        </LemonBanner>
    )
}

function IssueCard({ issue }: { issue: LogsAnomalyScanIssueApi }): JSX.Element {
    const verdict = VERDICT_TAG[issue.kind]
    return (
        <div className="rounded border bg-surface-primary p-3 flex flex-col gap-2" data-attr="logs-anomalies-issue">
            <div className="flex items-center gap-2">
                <LemonTag type={verdict.type}>{verdict.label}</LemonTag>
                {issue.severity ? <LemonTag type="muted">{issue.severity}</LemonTag> : null}
                {issue.state === 'active' ? (
                    <LemonTag type="danger">Ongoing</LemonTag>
                ) : issue.state === 'resolved' ? (
                    <LemonTag type="success">Resolved</LemonTag>
                ) : null}
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
                {issue.anomalous_bucket_times.length} anomalous{' '}
                {issue.anomalous_bucket_times.length === 1 ? 'bucket' : 'buckets'}
            </div>
        </div>
    )
}

function LearningStatus({ series }: { series: LogsAnomalyScanSeriesApi[] }): JSX.Element {
    const columns: LemonTableColumns<LogsAnomalyScanSeriesApi> = [
        {
            title: 'Severity',
            dataIndex: 'severity',
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
    return (
        <div className="flex flex-col gap-1">
            <h3 className="mb-0">What the detector has learned</h3>
            <LemonTable
                dataSource={series}
                columns={columns}
                rowKey="severity"
                size="small"
                emptyState="No log series found for this service in the scanned window."
                data-attr="logs-anomalies-learning"
            />
        </div>
    )
}
