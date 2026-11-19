import { useValues } from 'kea'

import { IconGraph, IconSparkles, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag, type LemonTagType, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { MonitoringCheckStateEnumApi, SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxReportDetailUrl } from '../../utils/inboxReportUrls'
import { monitoringEvidence, monitoringReadingOverdue } from '../../utils/monitoringTimeline'
import {
    monitoringDisplayState,
    monitoringFigures,
    monitoringSummaryTimeline,
    monitoringWindowProgress,
} from '../../utils/reportMonitoringSummary'
import { parsePrUrlParts, safeHttpUrl } from '../../utils/reportPresentation'
import { primaryReportPullRequest } from '../../utils/reportPullRequests'
import { ReportCheckMonitoringTimeline } from '../detail/ReportCheckMonitoringTimeline'
import { MonitoringEvidenceChart } from './MonitoringEvidenceChart'

const CHECK_STATE_TAG: Record<MonitoringCheckStateEnumApi, { label: string; type: LemonTagType }> = {
    passed: { label: 'Passed', type: 'success' },
    failed: { label: 'Failed', type: 'danger' },
    cancelled: { label: 'Cancelled', type: 'muted' },
    on_track: { label: 'On track', type: 'success' },
    not_on_track: { label: 'Not on track', type: 'warning' },
    awaiting_reading: { label: 'No reading yet', type: 'muted' },
    readings_hidden: { label: 'Readings hidden', type: 'muted' },
    final_check_only: { label: 'Checked at window end', type: 'default' },
}

const OUTCOME_HEADING: Record<string, string> = {
    resolved: 'Resolved: every check passed',
    resolved_by_assessment: 'Resolved: an agent confirmed the fix from other evidence',
    resolved_manually: 'Resolved by a person',
    closed: 'Closed: the fix was not shown to work',
}

function Time({ iso }: { iso: string }): JSX.Element {
    return <TZLabel time={iso} formatDate="MMM D" formatTime="h:mm A" />
}

function Fact({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex justify-between gap-3 text-xs">
            <span className="text-tertiary">{label}</span>
            <span className="text-right">{children}</span>
        </div>
    )
}

function Evidence({ report, now }: { report: SignalReportListApi; now: number }): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const outcome = report.monitoring_outcome
    if (outcome) {
        return (
            <div className="flex flex-col gap-1 rounded bg-surface-secondary p-3 text-sm">
                <div className="font-semibold">{OUTCOME_HEADING[outcome.kind]}</div>
                <div className="text-secondary">
                    Monitoring ended <Time iso={outcome.ended_at} />.
                </div>
                {outcome.follow_up ? (
                    <div>
                        Follow-up report:{' '}
                        <Link to={inboxReportDetailUrl(outcome.follow_up.report_id, urls.inbox('monitoring'))}>
                            {outcome.follow_up.title ?? 'Untitled report'}
                        </Link>
                    </div>
                ) : outcome.kind === 'closed' ? (
                    <div className="text-secondary">Follow-up research has been requested.</div>
                ) : null}
            </div>
        )
    }
    const summary = report.monitoring_summary
    if (!summary) {
        return (
            <div className="rounded bg-surface-secondary p-3 text-sm text-secondary">
                The follow-up checks run when this fix's window ends.
            </div>
        )
    }
    const lead = summary.lead_check
    const state = monitoringDisplayState(summary, now)
    const interval = lead?.metric_id ? report.metrics.find((m) => m.metric_id === lead.metric_id)?.interval : null
    const figures = monitoringFigures(summary, interval)
    const evidence = state === 'readings_hidden' ? null : monitoringEvidence(report, timezone)
    const nextReading = lead?.next_measurement_at
    return (
        <div className="flex flex-col gap-2">
            {lead ? <div className="text-xs font-semibold text-secondary">{lead.title}</div> : null}
            {evidence ? (
                <MonitoringEvidenceChart summary={summary} evidence={evidence} now={now} />
            ) : (
                <div className="flex flex-col gap-1 rounded bg-surface-secondary p-3 text-sm text-secondary">
                    {state === 'window_ended' ? (
                        'The window has ended. The final checks are running now.'
                    ) : state === 'readings_hidden' ? (
                        "You don't have access to the data this check measures, so its readings are hidden."
                    ) : state === 'final_check_only' ? (
                        <span>
                            The checks run when the window ends, <Time iso={summary.ends_at} />. Nothing is measured
                            before then.
                        </span>
                    ) : nextReading ? (
                        <span>
                            The next reading is due <Time iso={nextReading} />.
                        </span>
                    ) : null}
                    <ReportCheckMonitoringTimeline timeline={monitoringSummaryTimeline(summary, now)} />
                </div>
            )}
            {figures && (figures.before || figures.sinceFix) ? (
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-secondary">
                    <span>
                        Before the fix <span className="font-semibold text-primary">{figures.before ?? '–'}</span>
                    </span>
                    <span>
                        Since the fix <span className="font-semibold text-primary">{figures.sinceFix ?? '–'}</span>
                    </span>
                    <span className="text-tertiary">{figures.basis}</span>
                </div>
            ) : null}
            {monitoringReadingOverdue(report, now) && nextReading ? (
                <div className="flex items-center gap-1.5 text-xs text-warning">
                    <IconWarning className="size-3.5 shrink-0" />
                    A reading was due {dayjs(nextReading).from(dayjs(now))} and hasn't run yet. The verdict still runs
                    on time.
                </div>
            ) : null}
        </div>
    )
}

export function MonitoringRowDetail({ report, now }: { report: SignalReportListApi; now: number }): JSX.Element {
    const { user } = useValues(userLogic)
    const summary = report.monitoring_summary
    const assignee = report.assignee?.responsible_user ?? null
    const assignedToYou = !!user && assignee?.uuid === user.uuid
    const yourConnections = [
        assignedToYou ? 'Assigned to you' : null,
        report.is_suggested_reviewer ? 'Suggested reviewer' : null,
    ].filter(Boolean)
    const pullRequest = primaryReportPullRequest(report)
    const prUrl = safeHttpUrl(pullRequest.url)
    const prNumber = prUrl ? parsePrUrlParts(prUrl)?.number : null
    const progress = summary && !report.monitoring_outcome ? monitoringWindowProgress(summary, now) : null
    const checks = summary?.checks ?? []

    return (
        <div className="flex flex-col gap-3 rounded border border-primary bg-surface-primary p-4">
            <div className="flex flex-col gap-0.5">
                <div className="text-sm font-semibold">{report.title ?? 'Untitled report'}</div>
                {report.summary_lead ? <div className="text-sm text-secondary">{report.summary_lead}</div> : null}
            </div>
            <div className="flex flex-col gap-4 @2xl:flex-row">
                <div className="min-w-0 flex-1">
                    <Evidence report={report} now={now} />
                </div>
                <div className="flex flex-col gap-3 @2xl:w-72 @2xl:shrink-0">
                    <div className="flex flex-col gap-1">
                        {report.monitoring_started_at ? (
                            <Fact label="Started">
                                <Time iso={report.monitoring_started_at} />
                            </Fact>
                        ) : null}
                        {summary && !report.monitoring_outcome ? (
                            <Fact label="Verdict">
                                <Time iso={summary.ends_at} />
                            </Fact>
                        ) : null}
                        {progress ? <Fact label="Window">{progress}</Fact> : null}
                        {yourConnections.length ? <Fact label="You">{yourConnections.join(' · ')}</Fact> : null}
                        {assignee && !assignedToYou ? (
                            <Fact label="Assigned to">{assignee.first_name || assignee.email}</Fact>
                        ) : null}
                    </div>
                    {checks.length ? (
                        <div className="flex flex-col gap-1.5">
                            <div className="text-xs font-semibold text-secondary">
                                {checks.length === 1 ? 'Check' : `${checks.length} checks`}
                            </div>
                            {checks.map((check) => (
                                <div key={check.check_id} className="flex items-start gap-1.5 text-xs">
                                    {check.kind === 'metric_threshold' ? (
                                        <IconGraph className="mt-0.5 size-3.5 shrink-0 text-tertiary" />
                                    ) : (
                                        <IconSparkles className="mt-0.5 size-3.5 shrink-0 text-tertiary" />
                                    )}
                                    <span className="min-w-0 flex-1">{check.title}</span>
                                    <LemonTag
                                        size="small"
                                        type={CHECK_STATE_TAG[check.state].type}
                                        className="shrink-0"
                                    >
                                        {CHECK_STATE_TAG[check.state].label}
                                    </LemonTag>
                                </div>
                            ))}
                        </div>
                    ) : null}
                </div>
            </div>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    size="small"
                    type="primary"
                    to={inboxReportDetailUrl(report.id, urls.inbox('monitoring'))}
                    data-attr="inbox-monitoring-open-report"
                >
                    Open report
                </LemonButton>
                {prUrl ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        to={prUrl}
                        targetBlank
                        data-attr="inbox-monitoring-open-pr"
                    >
                        {prNumber ? `PR #${prNumber}` : 'Pull request'}
                    </LemonButton>
                ) : null}
            </div>
        </div>
    )
}
