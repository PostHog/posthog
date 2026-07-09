import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { cn } from 'lib/utils/css-classes'
import { dateMapping } from 'lib/utils/dateFilters'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EntityHeader, VerdictPill } from '../components/EntityHeader'
import { MetricTile } from '../components/MetricTile'
import { PullRequestTable } from '../components/PullRequestTable'
import { formatCost, formatMinutes } from '../components/runTables'
import { RepoScopeChip, ScopeBar } from '../components/ScopeBar'
import { Section } from '../components/Section'
import { AuthorLogicProps, authorLogic } from './authorLogic'
import { SHARED_DEFAULT_DATE_FROM, engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'

// date_from only (the list floors on it); "all time" / week+month snaps and Custom are out. Every option
// here stays within the list's 365d load window (max preset is 180d / YTD), so the client-side cost tiles
// are always a subset of the loaded PRs — a Custom range could reach past the load and desync the tiles
// from the server-windowed workflow breakdown.
const AUTHOR_DATE_OPTIONS = dateMapping.filter(({ key }) =>
    ['Last 7 days', 'Last 14 days', 'Last 30 days', 'Last 90 days', 'Last 180 days', 'Year to date'].includes(key)
)

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
        prs,
        prsLoading,
        windowedRows,
        totalCostUsd,
        totalBillableMinutes,
        totalLoops,
        openPrCount,
        workflowCosts,
        workflowCostsLoading,
        sourceId,
    } = useValues(authorLogic)
    const { dateFrom, dateTo } = useValues(engineeringAnalyticsFiltersLogic)
    const { setDateRange } = useActions(engineeringAnalyticsFiltersLogic)

    const hubUrl = combineUrl(urls.engineeringAnalytics(), sourceId ? { source: sourceId } : {}).url
    const avatarUrl = prs[0]?.authorAvatarUrl
    const costPerLoop = totalCostUsd != null && totalLoops > 0 ? totalCostUsd / totalLoops : null
    const workflowCostsTotal = workflowCosts.reduce((sum, c) => sum + (c.estimated_cost_usd ?? 0), 0)
    // Ranked, biggest spend first; the bar length is each workflow's share of the window's total.
    const rankedCosts = [...workflowCosts].sort((a, b) => (b.estimated_cost_usd ?? 0) - (a.estimated_cost_usd ?? 0))
    // A source can hold several repos, so the author's PRs may span repos. Only claim one repo (and link
    // per-workflow into it) when they all agree; otherwise the page is genuinely cross-repo.
    const repoSlugs = Array.from(new Set(prs.map((pr) => `${pr.repoOwner}/${pr.repoName}`)))
    const singleRepo = repoSlugs.length === 1 ? prs[0] : null

    return (
        <SceneContent>
            <SceneTitleSection name={handle} resourceType={{ type: 'health' }} />
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
                extra={
                    <DateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={(from, to) => setDateRange(from ?? SHARED_DEFAULT_DATE_FROM, to ?? null)}
                        dateOptions={AUTHOR_DATE_OPTIONS}
                        size="small"
                    />
                }
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
                    prsLoading ? undefined : <VerdictPill kind="muted">{pluralize(openPrCount, 'open PR')}</VerdictPill>
                }
            />
            {/* The author page is a way to find and explain one's own work — it lists this author's PRs and
                their CI cost. It carries no per-developer performance/ranking metric (no cycle time, no flaky
                score): the cost figures are transparent spend, not a scoreboard (SPEC §2). */}
            <div className="flex flex-col gap-4">
                {/* The scope-bar date picker scopes these cost tiles (and the breakdown below) only — the PR
                    list stays the author's recent PRs, loaded over a fixed year window. */}
                <div className="flex flex-wrap gap-2.5">
                    <MetricTile
                        label="Pull requests opened"
                        value={windowedRows.length.toLocaleString()}
                        sub="in the selected window"
                    />
                    <MetricTile
                        label="CI cost"
                        tooltip="Full CI cost of the PRs opened in the selected window, across each PR's whole history — not only runs inside the window. The 'Where their CI minutes go' breakdown below counts CI runs started in the window instead, so the two won't reconcile exactly."
                        value={formatCost(totalCostUsd)}
                        sub={
                            totalCostUsd != null
                                ? `${formatMinutes(totalBillableMinutes)} billable`
                                : 'no cost data yet'
                        }
                    />
                    <MetricTile
                        label="Cost per loop"
                        tooltip="A loop is one push and the CI it triggered. Cost per loop = total CI cost ÷ total pushes across the PRs opened in the window — the spend of one iteration, not a running total."
                        value={formatCost(costPerLoop)}
                        sub={
                            costPerLoop != null
                                ? `${totalLoops.toLocaleString()} loops in the window`
                                : 'no cost data yet'
                        }
                    />
                </div>

                <Section id="author-prs" title="Pull requests">
                    <PullRequestTable
                        rows={prs}
                        loading={prsLoading}
                        sourceId={sourceId}
                        costLensEnabled
                        showAuthor={false}
                        showCreated
                        dataAttr="engineering-analytics-author-pr-table"
                        emptyState={`No pull requests for ${handle} in the last year.`}
                    />
                </Section>

                <Section id="author-cost" title="Where their CI minutes go">
                    {workflowCostsLoading ? (
                        <LemonCard hoverEffect={false} className="p-4">
                            <LemonSkeleton className="mb-3 h-4 w-24" />
                            {Array.from({ length: 6 }).map((_, i) => (
                                <div
                                    key={i}
                                    className="flex items-center gap-4 border-b border-primary px-1 py-2.5 last:border-b-0"
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
                                const to = singleRepo
                                    ? combineUrl(
                                          urls.engineeringAnalyticsWorkflowRuns(
                                              singleRepo.repoOwner,
                                              singleRepo.repoName,
                                              cost.workflow_name
                                          ),
                                          sourceId ? { source: sourceId } : {}
                                      ).url
                                    : undefined
                                const row = (
                                    <div
                                        className={cn(
                                            'flex items-center gap-4 border-b border-primary px-1 py-2.5 last:border-b-0',
                                            to && 'cursor-pointer hover:bg-fill-button-tertiary-hover'
                                        )}
                                    >
                                        <div className="w-48 shrink-0 min-w-0">
                                            <span className="block truncate text-[13px] font-medium text-primary">
                                                {cost.workflow_name || '(unknown workflow)'}
                                            </span>
                                            <span className="block text-[11px] text-tertiary">
                                                {formatMinutes(cost.billable_minutes)} billable
                                            </span>
                                        </div>
                                        <LemonProgress
                                            percent={share * 100}
                                            strokeColor="var(--data-color-1)"
                                            bgColor="var(--color-bg-fill-tertiary)"
                                            smoothing={false}
                                            className="flex-1"
                                        />
                                        <div className="w-24 shrink-0 text-right">
                                            <span className="block text-[13px] font-semibold tabular-nums text-primary">
                                                {formatCost(usd)}
                                            </span>
                                            <span className="block text-[10px] tabular-nums text-tertiary">
                                                {Math.round(share * 100)}%
                                            </span>
                                        </div>
                                    </div>
                                )
                                const key = cost.workflow_name || '(unknown)'
                                return to ? (
                                    <Link key={key} to={to} className="block">
                                        {row}
                                    </Link>
                                ) : (
                                    <div key={key}>{row}</div>
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
            </div>
        </SceneContent>
    )
}

export default EngineeringAnalyticsAuthorScene
