import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { AppMetricsTimeSeriesResponse, appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { dayjs } from 'lib/dayjs'
import { percentage } from 'lib/utils/numbers'

import type { HogFlowBatchJob } from '../hogflows/types'
import { workflowSuggestionsAvailabilityLogic } from '../suggestions/workflowSuggestionsAvailabilityLogic'
import { WorkflowMetricCard } from '../WorkflowMetricCard'
import { METRIC_COLORS, withDisplayName, workflowMetricsSummaryLogic } from '../workflowMetricsSummaryLogic'
import { WorkflowMessageLeaderboard } from './WorkflowMessageLeaderboard'
import { WorkflowOverviewDetails } from './WorkflowOverviewDetails'
import { WorkflowOverviewFeedback } from './WorkflowOverviewFeedback'
import { WorkflowOverviewHealth } from './WorkflowOverviewHealth'
import { WorkflowOverviewInFlight } from './WorkflowOverviewInFlight'
import { workflowOverviewLogic } from './workflowOverviewLogic'
import { WorkflowOverviewSuggestions } from './WorkflowOverviewSuggestions'
import { WorkflowStepReach } from './WorkflowStepReach'

function total(series: AppMetricsTimeSeriesResponse | null): number {
    return series?.series.reduce((acc, s) => acc + s.values.reduce((a, v) => a + v, 0), 0) ?? 0
}

// One response with a line per channel, so the tile totals both and the sparkline splits them.
function byChannel(
    email: AppMetricsTimeSeriesResponse | null,
    push: AppMetricsTimeSeriesResponse | null,
    labels: { email: string; push: string }
): AppMetricsTimeSeriesResponse | null {
    const source = email ?? push
    if (!source) {
        return null
    }
    return {
        ...source,
        series: [
            { name: labels.email, values: email?.series[0]?.values ?? [] },
            { name: labels.push, values: push?.series[0]?.values ?? [] },
        ],
    }
}

const OPENED_SERIES_COLORS: Record<string, string> = {
    'Emails opened': METRIC_COLORS['Opened'],
    'Push notifications opened': METRIC_COLORS['Push notifications sent'],
}

function shareOf(part: number, whole: number, noun: string): JSX.Element | null {
    return whole > 0 ? <span className="text-muted">{`${percentage(part / whole, 1)} of ${noun}`}</span> : null
}

// A run keeps recording for as long as its people wait at delays, so the range stays open to now.
function runParams(run: HogFlowBatchJob): { dateFrom: string; interval: 'hour' | 'day' } {
    const start = dayjs(run.created_at)
    return {
        dateFrom: start.subtract(1, 'hour').toISOString(),
        interval: dayjs().diff(start, 'day') < 3 ? 'hour' : 'day',
    }
}

export interface WorkflowOverviewProps {
    id: string
    run?: HogFlowBatchJob
    previousRun?: HogFlowBatchJob | null
    controls?: ReactNode
}

export function WorkflowOverview({ id, run, previousRun, controls }: WorkflowOverviewProps): JSX.Element {
    const logicKey = run ? `hog-flow-overview-${id}-run-${run.id}` : `hog-flow-overview-${id}`
    const appSourceId = run?.id
    const period = run ? 'in this run' : 'in this date range'
    const previousLabel = previousRun ? `Previous run (${dayjs(previousRun.created_at).format('MMM D')})` : undefined
    const { getSingleTrendSeries: trendSeries, appMetricsTrendsLoading } = useValues(
        appMetricsLogic({
            logicKey,
            loadOnChanges: true,
            loadOnMount: true,
            // A date-shifted previous period holds no data for a run, so a run compares with the run before it.
            loadPreviousPeriod: !run,
            defaultParams: run ? runParams(run) : { dateFrom: '-30d', interval: 'day' },
            forceParams: { appSource: 'hog_flow', appSourceId: appSourceId ?? id, breakdownBy: 'metric_name' },
        })
    )
    const previousRunLogicKey = previousRun ? `${logicKey}-previous-${previousRun.id}` : undefined
    const { getSingleTrendSeries: previousRunSeries } = useValues(
        appMetricsLogic({
            logicKey: previousRunLogicKey ?? `${logicKey}-previous-none`,
            loadOnChanges: !!previousRun,
            loadOnMount: !!previousRun,
            loadPreviousPeriod: false,
            defaultParams: previousRun ? runParams(previousRun) : {},
            forceParams: { appSource: 'hog_flow', appSourceId: previousRun?.id ?? id, breakdownBy: 'metric_name' },
        })
    )
    const {
        messagingChannels,
        sentSummaryLabel,
        hasConversionGoal,
        convertedUsersUrl,
        conversionStats,
        conversionRate,
        conversionStatsLoading,
        conversionStatsFailed,
    } = useValues(workflowMetricsSummaryLogic({ logicKey, id, overview: true, appSourceId }))
    const { loadConversionStats } = useActions(
        workflowMetricsSummaryLogic({ logicKey, id, overview: true, appSourceId })
    )
    const { hasEmail, hasPush } = messagingChannels
    const overviewLogic = workflowOverviewLogic({ id, logicKey, previousRunLogicKey })
    const { trendsFailed, previousPeriodFailed, previousRunFailed, retrying } = useValues(overviewLogic)
    const comparisonFailed = run ? previousRunFailed : previousPeriodFailed
    // A failed comparison read leaves the old baseline in place, so the comparison is hidden instead.
    const getSingleTrendSeries = (name: string, previous?: boolean): AppMetricsTimeSeriesResponse | null =>
        previous && comparisonFailed
            ? null
            : run
              ? previous
                  ? previousRun
                      ? previousRunSeries(name)
                      : null
                  : trendSeries(name)
              : trendSeries(name, previous)
    const { retry } = useActions(overviewLogic)
    const retryAll = (): void => {
        retry()
        loadConversionStats({})
    }
    const { suggestionsAvailable } = useValues(workflowSuggestionsAvailabilityLogic)

    const sentFor = (previous?: boolean): AppMetricsTimeSeriesResponse | null =>
        hasEmail && hasPush
            ? byChannel(getSingleTrendSeries('email_sent', previous), getSingleTrendSeries('push_sent', previous), {
                  email: 'Emails sent',
                  push: 'Push notifications sent',
              })
            : withDisplayName(getSingleTrendSeries(hasPush ? 'push_sent' : 'email_sent', previous), sentSummaryLabel)
    const openedFor = (previous?: boolean): AppMetricsTimeSeriesResponse | null =>
        hasEmail && hasPush
            ? byChannel(getSingleTrendSeries('email_opened', previous), getSingleTrendSeries('push_opened', previous), {
                  email: 'Emails opened',
                  push: 'Push notifications opened',
              })
            : withDisplayName(getSingleTrendSeries(hasPush ? 'push_opened' : 'email_opened', previous), 'Opened')

    const started = withDisplayName(getSingleTrendSeries('triggered'), 'Workflows started')
    const sent = sentFor()
    const opened = openedFor()
    const clicked = withDisplayName(getSingleTrendSeries('email_link_clicked'), 'Link clicked')
    const converted = withDisplayName(getSingleTrendSeries('conversion'), 'Workflows converted')
    const sentTotal = total(sent)

    return (
        <div className="@container flex flex-col gap-4" data-attr="workflow-overview">
            <WorkflowOverviewFeedback />
            <div className="flex flex-wrap items-center justify-end gap-2">
                {controls ?? <AppMetricsFilters logicKey={logicKey} />}
            </div>
            {trendsFailed || comparisonFailed ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: retryAll,
                        loading: retrying,
                        'data-attr': 'workflow-overview-retry',
                    }}
                >
                    Couldn't load this workflow's metrics, so the numbers below may be missing.
                </LemonBanner>
            ) : null}

            <div className="flex flex-wrap gap-2" data-attr="workflow-overview-metric-cards">
                <WorkflowMetricCard
                    name="Started"
                    description={
                        run ? 'People this run started the workflow for.' : `Workflow runs that started ${period}.`
                    }
                    loading={appMetricsTrendsLoading}
                    timeSeries={started}
                    previousLabel={previousLabel}
                    previousPeriodTimeSeries={withDisplayName(
                        getSingleTrendSeries('triggered', true),
                        'Workflows started'
                    )}
                    color={METRIC_COLORS['Workflows started']}
                    colorIfZero={getColorVar('muted')}
                    compact
                />
                {hasEmail || hasPush ? (
                    <WorkflowMetricCard
                        name="Sent"
                        description={`${sentSummaryLabel} by this workflow ${period}.`}
                        loading={appMetricsTrendsLoading}
                        timeSeries={sent}
                        previousLabel={previousLabel}
                        previousPeriodTimeSeries={sentFor(true)}
                        color={METRIC_COLORS[sentSummaryLabel]}
                        seriesColors={METRIC_COLORS}
                        colorIfZero={getColorVar('muted')}
                        compact
                    />
                ) : null}
                {hasEmail || hasPush ? (
                    <WorkflowMetricCard
                        name="Opened"
                        description={`Opens recorded ${period}. Only tracked emails can record opens.`}
                        loading={appMetricsTrendsLoading}
                        timeSeries={opened}
                        previousLabel={previousLabel}
                        previousPeriodTimeSeries={openedFor(true)}
                        color={METRIC_COLORS['Opened']}
                        seriesColors={OPENED_SERIES_COLORS}
                        colorIfZero={getColorVar('muted')}
                        footer={shareOf(total(opened), sentTotal, 'sent')}
                        compact
                    />
                ) : null}
                {hasEmail ? (
                    <WorkflowMetricCard
                        name="Clicked"
                        description={`Email link clicks recorded ${period}.`}
                        loading={appMetricsTrendsLoading}
                        timeSeries={clicked}
                        previousLabel={previousLabel}
                        previousPeriodTimeSeries={withDisplayName(
                            getSingleTrendSeries('email_link_clicked', true),
                            'Link clicked'
                        )}
                        color={METRIC_COLORS['Link clicked']}
                        colorIfZero={getColorVar('muted')}
                        footer={shareOf(total(clicked), sentTotal, 'sent')}
                        compact
                    />
                ) : null}
                {hasConversionGoal ? (
                    <WorkflowMetricCard
                        name="Converted"
                        description={`Conversions recorded ${period} against the workflow's goal.`}
                        loading={appMetricsTrendsLoading}
                        timeSeries={converted}
                        previousLabel={previousLabel}
                        previousPeriodTimeSeries={withDisplayName(
                            getSingleTrendSeries('conversion', true),
                            'Workflows converted'
                        )}
                        color={METRIC_COLORS['Workflows converted']}
                        colorIfZero={getColorVar('muted')}
                        footer={
                            conversionStatsFailed ? (
                                <span className="flex flex-wrap items-center justify-center gap-x-2 text-muted">
                                    <span>Couldn't load conversions.</span>
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        onClick={() => loadConversionStats({})}
                                        loading={conversionStatsLoading}
                                        data-attr="workflow-overview-conversion-retry"
                                    >
                                        Try again
                                    </LemonButton>
                                </span>
                            ) : conversionStatsLoading ? null : conversionStats.started > 0 ? (
                                <span className="flex flex-wrap items-center justify-center gap-x-2">
                                    <span className="text-muted" data-attr="workflow-overview-conversion-rate">
                                        {`${percentage(Math.min(conversionRate, 1), 1)} conversion rate`}
                                    </span>
                                    {conversionStats.conversions > 0 ? (
                                        <Link to={convertedUsersUrl}>View converted people</Link>
                                    ) : null}
                                </span>
                            ) : null
                        }
                        compact
                    />
                ) : null}
            </div>

            <WorkflowOverviewHealth id={id} logicKey={logicKey} appSourceId={appSourceId} period={period} />

            <div className="grid grid-cols-1 items-start gap-4 @4xl:grid-cols-2">
                <div className="flex min-w-0 flex-col gap-4">
                    <WorkflowStepReach id={id} logicKey={logicKey} period={period} runId={appSourceId} />
                    <WorkflowOverviewDetails id={id} />
                </div>
                <div className="flex min-w-0 flex-col gap-4">
                    <WorkflowOverviewInFlight id={id} logicKey={logicKey} allRuns={!!run} />
                    {suggestionsAvailable ? <WorkflowOverviewSuggestions id={id} /> : null}
                    <WorkflowMessageLeaderboard id={id} logicKey={logicKey} appSourceId={appSourceId} />
                </div>
            </div>
        </div>
    )
}
