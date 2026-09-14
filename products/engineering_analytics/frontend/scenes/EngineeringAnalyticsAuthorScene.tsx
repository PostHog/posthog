import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { dateMapping } from 'lib/utils/dateFilters'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { AuthorComparisonCard } from '../components/AuthorComparisonCard'
import { AuthorLeadTimeCard } from '../components/AuthorLeadTimeCard'
import { AuthorPullRequestCountsCard } from '../components/AuthorPullRequestCountsCard'
import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { EntityHeader, VerdictPill } from '../components/EntityHeader'
import { PullRequestDayView } from '../components/PullRequestDayView'
import { ReadyToMergeCard } from '../components/ReadyToMergeCard'
import { RedTimeByCauseCard } from '../components/RedTimeByCauseCard'
import { formatCost, formatMinutes } from '../components/runTables'
import { RepoScopeChip, ScopeBar } from '../components/ScopeBar'
import { ScopePanel } from '../components/ScopePanel'
import { Section } from '../components/Section'
import { ShareRow } from '../components/ShareRow'
import { compactMinutes, compactUsd, percent } from '../lib/format'
import { AuthorLogicProps, authorLogic } from './authorLogic'
import { SHARED_DEFAULT_DATE_FROM, engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'

// Relative presets only: the backend caps a window at a year, and every preset here stays inside it.
const AUTHOR_DATE_OPTIONS = dateMapping.filter(({ key }) =>
    ['Last 7 days', 'Last 14 days', 'Last 30 days', 'Last 90 days', 'Last 180 days', 'This year'].includes(key)
)

const formatRatio = (value: number): string => value.toFixed(1)

export const scene: SceneExport<AuthorLogicProps> = {
    component: EngineeringAnalyticsAuthorScene,
    logic: authorLogic,
    paramsToProps: ({ params: { handle }, searchParams: { source } }) => ({
        handle: decodeURIComponent(handle),
        sourceId: source ?? null,
    }),
}

export function EngineeringAnalyticsAuthorScene(): JSX.Element {
    const {
        handle,
        sourceId,
        summary,
        summaryLoading,
        timelines,
        timelinesLoading,
        workflowCosts,
        workflowCostsLoading,
        loadFailed,
        dayViewAlignment,
        dayViewGroups,
        dayViewAxisDays,
        redTime,
        avatarUrl,
        repoSlugs,
    } = useValues(authorLogic)
    const { setDayViewAlignment, loadSummary, loadTimelines, loadWorkflowCosts } = useActions(authorLogic)
    const { dateFrom, dateTo } = useValues(engineeringAnalyticsFiltersLogic)
    const { setDateRange } = useActions(engineeringAnalyticsFiltersLogic)

    const hubUrl = combineUrl(urls.engineeringAnalytics(), sourceId ? { source: sourceId } : {}).url
    const summaryPending = summaryLoading && !summary
    const jobsEmpty = 'Cost appears once the workflow jobs table on this GitHub source is synced.'
    const noMerges = 'Nothing merged in the window.'
    const costEmpty = summary && !summary.jobs_available ? jobsEmpty : noMerges
    const reviewsEmpty =
        summary && !summary.review_data_available
            ? 'Sync the reviews table on this GitHub source to see pushes after the first approval.'
            : 'No approved pull requests merged in the window.'
    const workflowCostsTotal = workflowCosts.reduce((sum, c) => sum + (c.estimated_cost_usd ?? 0), 0)
    // Ranked, biggest spend first; the bar length is each workflow's share of the window's total.
    const rankedCosts = [...workflowCosts].sort((a, b) => (b.estimated_cost_usd ?? 0) - (a.estimated_cost_usd ?? 0))
    // Only claim one repo (and link per-workflow into it) when every listed pull request agrees.
    const singleRepo = repoSlugs.length === 1 ? timelines?.items[0]?.repo : null

    return (
        <SceneContent className="pb-16">
            <SceneTitleSection name="Author" resourceType={{ type: 'health' }} />
            <ScopeBar
                repoSlot={
                    <RepoScopeChip
                        label={
                            repoSlugs.length === 1 ? repoSlugs[0] : repoSlugs.length ? 'All repositories' : 'Repository'
                        }
                        to={hubUrl}
                    />
                }
                lensFilter={{ label: `author: ${handle}`, to: hubUrl }}
                showDate={false}
            />
            <EntityHeader
                icon={
                    avatarUrl ? (
                        <img src={avatarUrl} alt="" className="size-10 rounded-lg" />
                    ) : (
                        <Lettermark name={handle} />
                    )
                }
                title={handle}
                slug={
                    <Link to={`https://github.com/${encodeURIComponent(handle)}`} target="_blank" targetBlankIcon>
                        github.com/{handle}
                    </Link>
                }
                right={
                    summary ? (
                        <VerdictPill kind="muted">{pluralize(summary.open_pr_count, 'open PR')}</VerdictPill>
                    ) : undefined
                }
            />
            {/* The page explains one author's own friction against the repository. It never compares
                authors with each other (SPEC §2). */}
            {loadFailed ? (
                <CIAnalyticsLoadError
                    onRetry={() => {
                        loadSummary()
                        loadTimelines()
                        loadWorkflowCosts()
                    }}
                />
            ) : (
                <ScopePanel
                    busy={summaryLoading || timelinesLoading || workflowCostsLoading}
                    controls={
                        <DateFilter
                            dateFrom={dateFrom}
                            dateTo={dateTo}
                            onChange={(from, to) => setDateRange(from ?? SHARED_DEFAULT_DATE_FROM, to ?? null)}
                            dateOptions={AUTHOR_DATE_OPTIONS}
                            size="small"
                        />
                    }
                >
                    <Section id="author-spend" title="CI spend">
                        <div className="@container">
                            <div className="grid grid-cols-1 gap-2 @min-[36rem]:grid-cols-2 @min-[64rem]:grid-cols-4">
                                <AuthorPullRequestCountsCard summary={summary} loading={summaryPending} />
                                <AuthorComparisonCard
                                    title="CI cost per merged PR"
                                    tooltip="Median estimated CI cost of a merged pull request: every run linked to it, merge queue runs included, from up to 30 days before the window. Repo: the same median over every pull request merged in the repository, bots excluded."
                                    figure={summary?.cost_per_merged_pr_usd}
                                    formatValue={compactUsd}
                                    caption={
                                        summary?.total_cost_usd != null
                                            ? `${compactUsd(summary.total_cost_usd)} in total`
                                            : undefined
                                    }
                                    loading={summaryPending}
                                    emptyText={costEmpty}
                                />
                                <AuthorComparisonCard
                                    title="Billable minutes per merged PR"
                                    tooltip="Median billed runner minutes of a merged pull request, on the billed clock (machine boot left out). Re-run copies that never ran again are not counted."
                                    figure={summary?.billable_minutes_per_merged_pr}
                                    formatValue={compactMinutes}
                                    caption={
                                        summary?.total_billable_minutes != null
                                            ? `${compactMinutes(summary.total_billable_minutes)} billable in total`
                                            : undefined
                                    }
                                    loading={summaryPending}
                                    emptyText={costEmpty}
                                />
                                <AuthorComparisonCard
                                    title="Cost per push"
                                    tooltip="CI cost divided by pushes. A push is a new commit and the CI it started: the price of one iteration, so a high figure points at heavy workflows rather than many pushes."
                                    figure={summary?.cost_per_push_usd}
                                    formatValue={compactUsd}
                                    caption={summary ? pluralize(summary.push_count, 'push', 'pushes') : undefined}
                                    loading={summaryPending}
                                    emptyText={costEmpty}
                                />
                            </div>
                        </div>
                    </Section>

                    <Section id="author-merge" title="Getting merged">
                        <div className="@container">
                            <div className="grid grid-cols-1 gap-2 @min-[36rem]:grid-cols-2 @min-[64rem]:grid-cols-4">
                                <div className="@min-[36rem]:col-span-2">
                                    <ReadyToMergeCard summary={summary} loading={summaryPending} />
                                </div>
                                <AuthorComparisonCard
                                    title="Pushes after approval"
                                    tooltip="Average new commits pushed after the first approval, per merged pull request that had an approval."
                                    figure={summary?.pushes_after_approval_per_merged_pr}
                                    formatValue={formatRatio}
                                    loading={summaryPending}
                                    emptyText={reviewsEmpty}
                                />
                                <AuthorComparisonCard
                                    title="Merge queue attempts"
                                    tooltip="Average merge queue attempts per merged pull request that went through the queue. 1.0 means every pull request landed on its first try. A failed attempt also counts when another pull request ahead in the queue broke it: the queue's history isn't in the warehouse, so the two can't be told apart."
                                    figure={summary?.merge_queue_attempts_per_merged_pr}
                                    formatValue={formatRatio}
                                    caption={
                                        summary?.failed_merge_queue_share.author != null
                                            ? `${percent(summary.failed_merge_queue_share.author)} had a failed attempt · repo ${percent(summary.failed_merge_queue_share.repo)}`
                                            : undefined
                                    }
                                    loading={summaryPending}
                                    emptyText="No merged pull requests went through the merge queue in the window."
                                />
                            </div>
                        </div>
                    </Section>

                    <Section id="author-lead-time" title="Lead time to deploy">
                        <AuthorLeadTimeCard leadTime={summary?.lead_time} loading={summaryPending} />
                    </Section>

                    <Section id="author-pull-requests" title="Pull requests">
                        <div className="flex flex-col gap-2">
                            <RedTimeByCauseCard
                                redTime={redTime}
                                loading={timelinesLoading && !timelines}
                                jobsAvailable={!!timelines?.jobs_available}
                            />
                            <PullRequestDayView
                                timelines={timelines}
                                groups={dayViewGroups}
                                days={dayViewAxisDays}
                                alignment={dayViewAlignment}
                                onAlignmentChange={setDayViewAlignment}
                                loading={timelinesLoading}
                                sourceId={sourceId}
                            />
                        </div>
                    </Section>

                    <Section id="author-cost" title="Where their CI minutes go">
                        {workflowCostsLoading ? (
                            <LemonCard hoverEffect={false} className="p-4">
                                <LemonSkeleton className="mb-3 h-4 w-24" />
                                {Array.from({ length: 6 }).map((_, i) => (
                                    <div
                                        key={i}
                                        className="flex items-center gap-3 border-b border-primary px-1 py-2 last:border-b-0"
                                    >
                                        <div className="w-48 shrink-0">
                                            <LemonSkeleton className="h-3.5 w-32" />
                                            <LemonSkeleton className="mt-1.5 h-2.5 w-20" />
                                        </div>
                                        <LemonSkeleton className="h-2 flex-1" />
                                        <LemonSkeleton className="h-3.5 w-12 shrink-0" />
                                    </div>
                                ))}
                            </LemonCard>
                        ) : workflowCosts.length > 0 ? (
                            <LemonCard hoverEffect={false} className="p-4">
                                <div className="mb-2 flex items-center justify-between gap-2">
                                    <h3 className="m-0 text-xs font-semibold text-secondary">By workflow</h3>
                                    <span className="text-xs tabular-nums text-tertiary">
                                        {formatCost(workflowCostsTotal)} total
                                    </span>
                                </div>
                                {rankedCosts.slice(0, 8).map((cost) => {
                                    const usd = cost.estimated_cost_usd ?? 0
                                    const share = workflowCostsTotal > 0 ? usd / workflowCostsTotal : 0
                                    return (
                                        <ShareRow
                                            key={cost.workflow_name || '(unknown)'}
                                            label={cost.workflow_name || '(unknown workflow)'}
                                            sub={`${formatMinutes(cost.billable_minutes)} billable`}
                                            value={formatCost(usd)}
                                            valueSub={`${Math.round(share * 100)}%`}
                                            share={share}
                                            color="var(--data-color-1)"
                                            fullWidthBar
                                            to={
                                                singleRepo
                                                    ? combineUrl(
                                                          urls.engineeringAnalyticsWorkflowRuns(
                                                              singleRepo.owner,
                                                              singleRepo.name,
                                                              cost.workflow_name
                                                          ),
                                                          sourceId ? { source: sourceId } : {}
                                                      ).url
                                                    : undefined
                                            }
                                        />
                                    )
                                })}
                                {workflowCosts.length > 8 && (
                                    <div className="pt-2 text-xs text-tertiary">
                                        +{workflowCosts.length - 8} more{' '}
                                        {pluralize(workflowCosts.length - 8, 'workflow', undefined, false)}, not shown
                                    </div>
                                )}
                            </LemonCard>
                        ) : (
                            <span className="text-xs text-secondary">
                                No cost data yet. The job-level source isn't synced, or nothing ran in the window.
                            </span>
                        )}
                    </Section>
                </ScopePanel>
            )}
        </SceneContent>
    )
}

export default EngineeringAnalyticsAuthorScene
