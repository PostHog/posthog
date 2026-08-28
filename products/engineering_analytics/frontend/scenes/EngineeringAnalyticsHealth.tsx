import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'
import { TimeSeriesBarChart, useChartTheme, type TimeInterval } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { MergeToDeployBoxPlot } from '../components/MergeToDeployBoxPlot'
import { MetricTile, percentChange, pointChange } from '../components/MetricTile'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { Section } from '../components/Section'
import { compactAgeLabel } from '../lib/format'
import { doraLogic } from './doraLogic'

export function EngineeringAnalyticsHealth(): JSX.Element {
    const {
        notConnected,
        dora,
        doraLoading,
        doraFailed,
        environment,
        githubTeam,
        boxPlotBuckets,
        frequencyCounts,
        frequencyIsoLabels,
        environmentScopeLabel,
        environmentOptions,
        githubTeamOptions,
    } = useValues(doraLogic)
    const { setEnvironment, setGithubTeam, loadDora } = useActions(doraLogic)
    const chartTheme = useChartTheme()
    const frequencySeries = useMemo(
        () => [{ key: 'deployments', label: 'Deployments', data: frequencyCounts }],
        [frequencyCounts]
    )

    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (doraFailed) {
        return <CIAnalyticsLoadError onRetry={loadDora} />
    }

    const firstLoad = doraLoading && !dora
    const deployDataMissing = !!dora && !dora.deploy_data_available

    return (
        <div className="flex flex-col gap-4">
            <ScopeBar repoSlot={<SourceScopeChip />} />
            {deployDataMissing ? (
                <div data-attr="engineering-analytics-dora-no-deploy-data">
                    <LemonBanner type="info">
                        Deploy data isn't synced yet. Enable the deployments and deployment statuses endpoints on your
                        GitHub source to see DORA metrics.
                    </LemonBanner>
                </div>
            ) : (
                <div className="flex flex-wrap items-center gap-2">
                    <LemonSelect
                        size="small"
                        value={environment}
                        onChange={setEnvironment}
                        options={environmentOptions}
                        data-attr="engineering-analytics-dora-environment-select"
                    />
                    {dora?.has_membership_data && (
                        <LemonSelect
                            size="small"
                            value={githubTeam}
                            onChange={setGithubTeam}
                            options={githubTeamOptions}
                            data-attr="engineering-analytics-dora-team-select"
                        />
                    )}
                    {githubTeam && (
                        <span className="text-xs text-tertiary">
                            The team filter narrows the merge to deploy figures. Deploy counts stay repo-wide.
                        </span>
                    )}
                    {dora?.latest_deploy_status_at && (
                        <span
                            className="ml-auto text-xs text-tertiary"
                            data-attr="engineering-analytics-dora-freshness"
                        >
                            Latest deploy status synced {dayjs(dora.latest_deploy_status_at).fromNow()}.
                        </span>
                    )}
                </div>
            )}
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
                <MetricTile
                    label="Deployment frequency"
                    tooltip={`Successful deployments per day in the ${environmentScopeLabel} scope: ${dora?.deployment_count ?? 0} in this window.`}
                    value={dora?.deployments_per_day != null ? `${dora.deployments_per_day.toFixed(1)}/day` : '—'}
                    delta={{ value: percentChange(dora?.deployments_per_day, dora?.deployments_per_day_prev) }}
                    sub={
                        dora && dora.deploy_data_available && dora.deployment_count === 0
                            ? 'No successful deployments in this window.'
                            : undefined
                    }
                    loading={firstLoad}
                />
                <MetricTile
                    label="Merge to deploy"
                    tooltip={`Median wait from a PR's merge to the first successful deployment containing it, over ${dora?.deployed_pr_count ?? 0} deployed PRs (bots and drafts excluded). Not full commit-to-deploy lead time: pre-merge time is on the Overview tab.`}
                    value={
                        dora?.median_merge_to_deploy_seconds != null
                            ? compactAgeLabel(dora.median_merge_to_deploy_seconds)
                            : '—'
                    }
                    delta={{
                        value: percentChange(
                            dora?.median_merge_to_deploy_seconds,
                            dora?.median_merge_to_deploy_seconds_prev
                        ),
                        goodWhenDown: true,
                    }}
                    sub={
                        dora && dora.median_merge_to_deploy_seconds == null
                            ? 'No PRs were deployed in this window.'
                            : undefined
                    }
                    loading={firstLoad}
                />
                <MetricTile
                    label="Failed deployment share"
                    tooltip={`Deployments with a failure or error status over deployments that reached an outcome (${dora?.failed_deployment_count ?? 0} failed here). A change failure proxy: deploys that succeeded but broke production aren't counted, because no incident data is linked.`}
                    value={
                        dora?.failed_deployment_share != null
                            ? `${(dora.failed_deployment_share * 100).toFixed(1)}%`
                            : '—'
                    }
                    delta={{
                        value: pointChange(dora?.failed_deployment_share, dora?.failed_deployment_share_prev),
                        unit: 'pt',
                        goodWhenDown: true,
                    }}
                    sub={
                        dora && dora.failed_deployment_share == null
                            ? 'No deployments reached an outcome in this window.'
                            : undefined
                    }
                    loading={firstLoad}
                />
                <MetricTile
                    label="Failed deploy to next success"
                    tooltip="Median wait from a deployment's first failure status to the next successful deployment in the same environment. A time to restore proxy: recovery by anything other than a deploy is invisible, and unrecovered failures are excluded."
                    value={
                        dora?.median_failed_deploy_to_next_success_seconds != null
                            ? compactAgeLabel(dora.median_failed_deploy_to_next_success_seconds)
                            : '—'
                    }
                    delta={{
                        value: percentChange(
                            dora?.median_failed_deploy_to_next_success_seconds,
                            dora?.median_failed_deploy_to_next_success_seconds_prev
                        ),
                        goodWhenDown: true,
                    }}
                    sub={
                        dora && dora.median_failed_deploy_to_next_success_seconds == null
                            ? 'No failed deployment recovered in this window.'
                            : undefined
                    }
                    loading={firstLoad}
                />
            </div>
            <Section
                id="merge-to-deploy"
                title="Merge to deploy distribution"
                note="Box per bucket: whisker min to max, box p25 to p75, line at the median, dot at the mean. Buckets key on deploy time."
                busy={doraLoading && !!dora}
            >
                {firstLoad ? (
                    <LemonSkeleton className="h-40 w-full" />
                ) : boxPlotBuckets.length === 0 ? (
                    <div className="py-8 text-center text-sm text-secondary">
                        {githubTeam && dora && !dora.has_membership_data
                            ? 'Team membership data is not synced, so the team filter cannot be applied.'
                            : 'No deploy data for this window.'}
                    </div>
                ) : (
                    <>
                        <div data-attr="engineering-analytics-dora-box-plot">
                            <MergeToDeployBoxPlot buckets={boxPlotBuckets} formatSeconds={compactAgeLabel} />
                        </div>
                        {dora?.unattributed_merged_pr_share != null && dora.unattributed_merged_pr_share > 0 && (
                            <div
                                className="mt-2 text-xs text-tertiary"
                                data-attr="engineering-analytics-dora-unattributed"
                            >
                                {(dora.unattributed_merged_pr_share * 100).toFixed(1)}% of the {dora.merged_pr_count}{' '}
                                PRs merged in this window have no deploy attributed yet, usually because their deploy
                                hasn't happened or synced.
                            </div>
                        )}
                    </>
                )}
            </Section>
            <Section
                id="deployment-frequency"
                title="Deployments over time"
                note={`Successful deployments per bucket in the ${environmentScopeLabel} scope.`}
                busy={doraLoading && !!dora}
            >
                {firstLoad ? (
                    <LemonSkeleton className="h-40 w-full" />
                ) : frequencyCounts.length === 0 ? (
                    <div className="py-8 text-center text-sm text-secondary">No deploy data for this window.</div>
                ) : (
                    // The chart's root is a `flex-1` child, so the sized wrapper must be a flex column.
                    <div className="flex h-40 flex-col" data-attr="engineering-analytics-dora-frequency-chart">
                        <TimeSeriesBarChart
                            series={frequencySeries}
                            labels={frequencyIsoLabels}
                            theme={chartTheme}
                            config={{
                                xAxis: {
                                    timezone: 'UTC',
                                    interval: (dora?.series_granularity ?? 'day') as TimeInterval,
                                },
                                yAxis: { format: 'numeric', decimalPlaces: 0 },
                                minBarSize: 2,
                            }}
                        />
                    </div>
                )}
            </Section>
        </div>
    )
}
