import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { FailureSparkline } from '../components/FailureSparkline'
import { MergeToDeployBoxPlot } from '../components/MergeToDeployBoxPlot'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { Section } from '../components/Section'
import { WindowComparisonCard } from '../components/WindowComparisonCard'
import { compactAgeLabel } from '../lib/format'
import { doraLogic } from './doraLogic'

export function EngineeringAnalyticsDora(): JSX.Element {
    const {
        notConnected,
        dora,
        doraLoading,
        doraFailed,
        environment,
        githubTeam,
        boxPlotBuckets,
        frequencyCounts,
        frequencyLabels,
    } = useValues(doraLogic)
    const { setEnvironment, setGithubTeam, loadDora } = useActions(doraLogic)

    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (doraFailed) {
        return <CIAnalyticsLoadError onRetry={loadDora} />
    }

    const firstLoad = doraLoading && !dora
    const deployDataMissing = !!dora && !dora.deploy_data_available

    const scopeLabel =
        !dora || dora.environment_scope === 'production'
            ? 'production'
            : dora.environment_scope === 'persistent'
              ? 'all persistent environments'
              : dora.environment_scope
    const environmentOptions = [
        {
            value: null as string | null,
            label: dora?.environment_scope === 'persistent' ? 'All persistent environments' : 'Production',
        },
        ...(dora?.environments ?? []).map((name) => ({ value: name as string | null, label: name })),
    ]
    const teamOptions = [
        { value: null as string | null, label: 'All teams' },
        ...(dora?.github_teams ?? []).map((slug) => ({ value: slug as string | null, label: slug })),
    ]

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
                            options={teamOptions}
                            data-attr="engineering-analytics-dora-team-select"
                        />
                    )}
                    {githubTeam && (
                        <span className="text-xs text-tertiary">
                            The team filter narrows the merge to deploy figures. Deploy counts stay repo-wide.
                        </span>
                    )}
                </div>
            )}
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
                <WindowComparisonCard
                    title="Deployment frequency"
                    value={dora?.deployments_per_day}
                    previousValue={dora?.deployments_per_day_prev}
                    formatValue={(value) => `${value.toFixed(1)}/day`}
                    tooltip={`Successful deployments per day in the ${scopeLabel} scope: ${dora?.deployment_count ?? 0} in this window.`}
                    loading={firstLoad}
                    emptyText="No successful deployments in this window."
                />
                <WindowComparisonCard
                    title="Merge to deploy"
                    value={dora?.median_merge_to_deploy_seconds}
                    previousValue={dora?.median_merge_to_deploy_seconds_prev}
                    formatValue={compactAgeLabel}
                    goodWhenDown
                    tooltip={`Median wait from a PR's merge to the first successful deployment after it, over ${dora?.deployed_pr_count ?? 0} deployed PRs (bots and drafts excluded). Not full commit-to-deploy lead time: pre-merge time is on the Overview tab.`}
                    loading={firstLoad}
                    emptyText="No PRs were deployed in this window."
                />
                <WindowComparisonCard
                    title="Failed deployment share"
                    value={dora?.failed_deployment_share}
                    previousValue={dora?.failed_deployment_share_prev}
                    formatValue={(value) => `${(value * 100).toFixed(1)}%`}
                    deltaUnit="pt"
                    goodWhenDown
                    tooltip={`Deployments with a failure or error status over deployments that reached an outcome (${dora?.failed_deployment_count ?? 0} failed here). A change failure proxy: deploys that succeeded but broke production aren't counted, because no incident data is linked.`}
                    loading={firstLoad}
                    emptyText="No deployments reached an outcome in this window."
                />
                <WindowComparisonCard
                    title="Failed deploy to next success"
                    value={dora?.median_failed_deploy_to_next_success_seconds}
                    previousValue={dora?.median_failed_deploy_to_next_success_seconds_prev}
                    formatValue={compactAgeLabel}
                    goodWhenDown
                    tooltip="Median wait from a deployment's first failure status to the next successful deployment in the same environment. A time to restore proxy: recovery by anything other than a deploy is invisible, and unrecovered failures are excluded."
                    loading={firstLoad}
                    emptyText="No failed deployment recovered in this window."
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
                    <div data-attr="engineering-analytics-dora-box-plot">
                        <MergeToDeployBoxPlot buckets={boxPlotBuckets} formatSeconds={compactAgeLabel} />
                    </div>
                )}
            </Section>
            <Section
                id="deployment-frequency"
                title="Deployments over time"
                note={`Successful deployments per bucket in the ${scopeLabel} scope.`}
                busy={doraLoading && !!dora}
            >
                {firstLoad ? (
                    <LemonSkeleton className="h-8 w-full" />
                ) : frequencyCounts.length === 0 ? (
                    <div className="py-8 text-center text-sm text-secondary">No deploy data for this window.</div>
                ) : (
                    <FailureSparkline
                        completed={frequencyCounts}
                        failures={frequencyCounts.map(() => 0)}
                        labels={frequencyLabels}
                        ariaLabel="Successful deployments per bucket"
                    />
                )}
            </Section>
        </div>
    )
}
