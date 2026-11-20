import clsx from 'clsx'
import { useValues } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import {
    MonitoringSummaryStateEnumApi,
    type ReportMetricApi,
    type ReportMonitoringSummaryApi,
} from 'products/signals/frontend/generated/api.schemas'

import {
    MONITORING_SUMMARY_TAGS,
    monitoringDisplayState,
    monitoringFigures,
    monitoringSummaryTimeline,
    monitoringTrend,
} from '../../utils/reportMonitoringSummary'
import { ReportCheckMonitoringTimeline } from '../detail/ReportCheckMonitoringTimeline'
import { ReportCardMonitoringTrend } from './ReportCardMonitoringTrend'

const SINCE_FIX_TEXT: Partial<Record<ReportMonitoringSummaryApi['state'], string>> = {
    not_on_track: 'text-warning',
    on_track: 'text-success',
}

/** List metrics carry their bucket size; detail metrics carry the whole query instead. */
function metricInterval(metric: ReportMetricApi | undefined): string | null {
    const interval = metric && 'interval' in metric ? metric.interval : null
    return typeof interval === 'string' ? interval : null
}

/**
 * A Monitoring row's evidence: the report metric split at the fix, the before and since-fix figures,
 * the state against the target, and the window strip from the report detail.
 */
export function ReportCardMonitoringPanel({
    summary,
    metrics,
    now,
}: {
    summary: ReportMonitoringSummaryApi
    metrics?: ReportMetricApi[]
    now: number
}): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const lead = summary.lead_check
    const metric = lead?.metric_id ? metrics?.find((candidate) => candidate.metric_id === lead.metric_id) : undefined
    const interval = metricInterval(metric)
    const trend = monitoringTrend(summary, metric ? { ...metric, interval } : undefined, timezone)
    const figures = monitoringFigures(summary, interval)
    const state = monitoringDisplayState(summary, now)
    const tag = MONITORING_SUMMARY_TAGS[state]

    return (
        <div className="flex w-full shrink-0 flex-col gap-1.5 @lg:w-56" data-attr="report-card-monitoring-panel">
            {trend ? <ReportCardMonitoringTrend trend={trend} state={state} /> : null}
            {!lead ? (
                <div className="flex min-h-10 items-center justify-center rounded border border-dashed border-primary px-2 text-center text-xs text-tertiary">
                    {state === MonitoringSummaryStateEnumApi.WindowEnded
                        ? 'The final checks are running'
                        : `Final checks run ${dayjs(summary.ends_at).format('MMM D')}`}
                </div>
            ) : null}
            {figures && (figures.before || figures.sinceFix) ? (
                <div className="flex items-baseline justify-between gap-2 text-[11px] leading-tight tabular-nums text-tertiary">
                    <span>
                        Before <span className="font-semibold text-secondary">{figures.before ?? '–'}</span>
                    </span>
                    <span aria-hidden>→</span>
                    <span className="text-right">
                        Since fix{' '}
                        <span className={clsx('font-semibold', SINCE_FIX_TEXT[state] ?? 'text-secondary')}>
                            {figures.sinceFix ?? '–'}
                        </span>
                    </span>
                </div>
            ) : null}
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <Tooltip title={tag.description} openOnClick>
                    <button
                        type="button"
                        className="inline-flex shrink-0 cursor-help rounded"
                        data-attr="report-card-monitoring-state"
                        // The row is a link: a tap that opens this explanation must not also open the report.
                        onClick={(event) => {
                            event.preventDefault()
                            event.stopPropagation()
                        }}
                    >
                        <LemonTag size="small" type={tag.type}>
                            {tag.label}
                        </LemonTag>
                    </button>
                </Tooltip>
                {figures ? (
                    <span className="min-w-0 text-[11px] leading-tight text-tertiary">{figures.basis}</span>
                ) : null}
            </div>
            <ReportCheckMonitoringTimeline timeline={monitoringSummaryTimeline(summary, now)} />
        </div>
    )
}
