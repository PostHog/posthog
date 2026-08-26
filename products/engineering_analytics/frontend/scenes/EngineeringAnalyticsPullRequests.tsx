import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { DeliveryPipeline } from '../components/DeliveryPipeline'
import { RepoEntityHeader } from '../components/EntityHeader'
import { PullRequestTable } from '../components/PullRequestTable'
import { ScopePanel } from '../components/ScopePanel'
import { Section } from '../components/Section'
import { HeroStat } from '../components/StatCard'
import { WindowComparisonCard } from '../components/WindowComparisonCard'
import { compactAgeLabel, compactHoursLabel, percent } from '../lib/format'
import { doraLogic } from './doraLogic'
import { CIStatusFilter, PRStateFilter, engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { timeToProductionLogic } from './timeToProductionLogic'

export function EngineeringAnalyticsPullRequests(): JSX.Element {
    const {
        cards,
        cardsLoading,
        filteredPullRequests,
        pullRequestsLoading,
        tableTruncated,
        stateFilter,
        ciStatusFilter,
        search,
        hasActiveFilters,
        activeCard,
        readyCount,
        thrashCount,
        sourceId,
        activeSource,
        notConnected,
        pullRequestsLoadError,
    } = useValues(engineeringAnalyticsLogic)
    const { setStateFilter, setCiStatusFilter, setSearch, resetFilters, applyCardFilter, refresh } =
        useActions(engineeringAnalyticsLogic)
    const { timing, timingLoading } = useValues(timeToProductionLogic)
    const { dora, doraLoading } = useValues(doraLogic)

    const pipeline = timing?.delivery_pipeline
    const deploysSynced = !!dora?.deploy_data_available
    const mergeToDeploy =
        deploysSynced && dora
            ? { medianSeconds: dora.median_merge_to_deploy_seconds ?? null, prCount: dora.deployed_pr_count }
            : null
    // timingLoading with nothing on screen is the first fetch; the cards show a skeleton rather than
    // an empty state, which would read as "nothing merged".
    const timingPending = timingLoading && !timing
    // Cycle time is ready->merge when the backend observed the draft/ready transitions; otherwise
    // it falls back to the coarse created->merged span, labeled as such.
    const cycleTime =
        timing?.median_ready_to_merge_seconds != null
            ? {
                  title: 'Median time from ready for review to merge',
                  value: timing.median_ready_to_merge_seconds,
                  previousValue: timing.median_ready_to_merge_seconds_prev,
                  tooltip:
                      'Median ready-for-review to merged time, bots and drafts excluded. Time as a draft is not counted.',
              }
            : {
                  title: 'Median time from open to merge',
                  value: timing?.median_open_to_merge_seconds,
                  previousValue: timing?.median_open_to_merge_seconds_prev,
                  tooltip:
                      'Median created-to-merged time, bots and drafts excluded. Coarse: draft and ready time are fused.',
              }

    // A 400 means no GitHub source — prompt to connect. A non-400 failure of this scene's data (cards or
    // the PR list) shows a retryable error, never the misleading "connect" state.
    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (pullRequestsLoadError) {
        return <CIAnalyticsLoadError onRetry={refresh} />
    }

    return (
        <div className="flex flex-col gap-4">
            <RepoEntityHeader repoFullName={activeSource?.repo || ''} />

            {/* The panel is the scope. Everything below it is the current open backlog, not windowed. */}
            <ScopePanel busy={timingLoading && !!timing}>
                <Section id="delivery" title="Time to production" busy={timingLoading}>
                    <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                        <WindowComparisonCard
                            title={cycleTime.title}
                            value={cycleTime.value}
                            previousValue={cycleTime.previousValue}
                            formatValue={compactHoursLabel}
                            goodWhenDown
                            loading={timingPending}
                            tooltip={cycleTime.tooltip}
                            emptyText="No PRs merged in the window yet."
                        />
                        <WindowComparisonCard
                            title="Median time from merge to production"
                            value={dora?.median_merge_to_deploy_seconds}
                            previousValue={dora?.median_merge_to_deploy_seconds_prev}
                            formatValue={compactAgeLabel}
                            goodWhenDown
                            loading={doraLoading && !dora}
                            tooltip="Median wait from a PR's merge to the first successful production deploy containing it, resolved through the deploy head commit. The same measure as the Health tab."
                            emptyText={
                                dora && !dora.deploy_data_available
                                    ? 'Production timing appears once the deployments source is synced.'
                                    : 'No PR merged in the window has reached production yet.'
                            }
                        />
                    </div>
                    <DeliveryPipeline pipeline={pipeline} mergeToDeploy={mergeToDeploy} loading={timingPending} />
                </Section>

                <Section id="merge-queue" title="Merge queue" busy={timingLoading}>
                    {timing &&
                    timing.merge_queue_merged_pr_count === 0 &&
                    timing.merge_queue_failed_or_cancelled_share == null ? (
                        <LemonCard hoverEffect={false} className="p-4 text-xs text-secondary">
                            No merge queue activity in the window.
                        </LemonCard>
                    ) : (
                        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                            <WindowComparisonCard
                                title="Merges retried in the queue"
                                tooltip="Share of queue-landed merges that needed more than one gate attempt. Bisection branches count toward the attempt they investigate."
                                value={timing?.merge_queue_multi_attempt_merge_share}
                                previousValue={timing?.merge_queue_multi_attempt_merge_share_prev}
                                formatValue={percent}
                                deltaUnit="pt"
                                goodWhenDown
                                loading={timingPending}
                                emptyText="No queue-landed merges in the window."
                            />
                            {timing?.merge_queue_trunk_available ? (
                                <WindowComparisonCard
                                    title="Left the queue unmerged"
                                    tooltip="Share of concluded merge queue entries that ended failed or cancelled, from the queue's own records."
                                    value={timing?.merge_queue_failed_or_cancelled_share}
                                    previousValue={timing?.merge_queue_failed_or_cancelled_share_prev}
                                    formatValue={(v) => percent(v, 1)}
                                    deltaUnit="pt"
                                    goodWhenDown
                                    loading={timingPending}
                                    emptyText="No concluded queue entries in the window."
                                />
                            ) : (
                                <WindowComparisonCard
                                    title="Merges with a failed queue run"
                                    tooltip="Share of queue-landed merges where at least one gate run failed before the merge. Derived from CI run conclusions, not the queue's own eviction records."
                                    value={timing?.merge_queue_failed_gate_merge_share}
                                    previousValue={timing?.merge_queue_failed_gate_merge_share_prev}
                                    formatValue={percent}
                                    deltaUnit="pt"
                                    goodWhenDown
                                    loading={timingPending}
                                    emptyText="No queue-landed merges in the window."
                                />
                            )}
                        </div>
                    )}
                </Section>
            </ScopePanel>

            <div className="flex flex-wrap items-center gap-1">
                <HeroStat
                    label="Open PRs"
                    value={cards?.openPrs ?? null}
                    align="start"
                    loading={cardsLoading}
                    onClick={() => applyCardFilter('open')}
                    active={activeCard === 'open'}
                    filterHint="Show all open PRs"
                />
                <span className="mx-1 h-8 w-px bg-border" />
                <HeroStat
                    label="Failing CI"
                    value={cards?.failingCi ?? null}
                    tone="danger"
                    align="start"
                    loading={cardsLoading}
                    onClick={() => applyCardFilter('failing')}
                    active={activeCard === 'failing'}
                    filterHint="Show open PRs with failing CI"
                />
                <HeroStat
                    label="Stuck >7d"
                    value={cards?.stuck ?? null}
                    tone="warning"
                    align="start"
                    loading={cardsLoading}
                    onClick={() => applyCardFilter('stuck')}
                    active={activeCard === 'stuck'}
                    filterHint="Show PRs stuck open over 7 days (excludes drafts and bots)"
                />
                <HeroStat
                    label="CI thrash"
                    value={thrashCount}
                    tone="warning"
                    align="start"
                    loading={pullRequestsLoading}
                    onClick={() => applyCardFilter('thrash')}
                    active={activeCard === 'thrash'}
                    filterHint="Show open PRs burning re-run cycles"
                />
                <HeroStat
                    label="Ready"
                    value={readyCount}
                    tone="success"
                    align="start"
                    loading={pullRequestsLoading}
                    onClick={() => applyCardFilter('ready')}
                    active={activeCard === 'ready'}
                    filterHint="Show open, non-draft PRs with green CI"
                />
            </div>

            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search title, repo, author, #id…"
                    value={search}
                    onChange={setSearch}
                    className="w-80"
                />
                <LemonSegmentedButton
                    size="small"
                    value={stateFilter}
                    onChange={(value) => setStateFilter(value as PRStateFilter)}
                    options={[
                        { value: 'open', label: 'Open' },
                        { value: 'draft', label: 'Draft' },
                        { value: 'merged', label: 'Merged' },
                        { value: 'closed', label: 'Closed' },
                        { value: 'all', label: 'All' },
                    ]}
                />
                <LemonSelect
                    size="small"
                    value={ciStatusFilter}
                    onChange={(value) => setCiStatusFilter(value as CIStatusFilter)}
                    options={[
                        { value: 'all', label: 'CI: any', labelInMenu: 'Any' },
                        { value: 'passing', label: 'CI: passing', labelInMenu: 'Passing' },
                        { value: 'failing', label: 'CI: failing', labelInMenu: 'Failing' },
                        { value: 'running', label: 'CI: running', labelInMenu: 'Running' },
                        { value: 'none', label: 'CI: none', labelInMenu: 'No CI' },
                    ]}
                />
            </div>

            <PullRequestTable
                rows={filteredPullRequests}
                loading={pullRequestsLoading}
                sourceId={sourceId}
                showCreated
                emptyState={
                    hasActiveFilters ? (
                        <div className="flex flex-col items-center gap-2">
                            <span>No pull requests match these filters.</span>
                            <LemonButton type="secondary" size="small" onClick={resetFilters}>
                                Clear filters
                            </LemonButton>
                        </div>
                    ) : (
                        "No pull requests yet. They'll appear once the GitHub source syncs."
                    )
                }
            />

            {tableTruncated && <div className="text-xs text-tertiary">Showing the most recent 1000 pull requests.</div>}
        </div>
    )
}
