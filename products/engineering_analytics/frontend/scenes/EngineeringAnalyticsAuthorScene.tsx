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

import { EntityHeader, VerdictPill } from '../components/EntityHeader'
import { formatCost, formatMinutes } from '../components/runTables'
import { RepoScopeChip, ScopeBar } from '../components/ScopeBar'
import { ScopePanel } from '../components/ScopePanel'
import { Section } from '../components/Section'
import { ShareRow } from '../components/ShareRow'
import { AuthorLogicProps, authorLogic } from './authorLogic'
import { DeliverySections } from './DeliverySections'
import { deliverySummaryLogic } from './deliverySummaryLogic'
import { SHARED_DEFAULT_DATE_FROM, engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import { pullRequestTimelinesLogic } from './pullRequestTimelinesLogic'

// Relative presets only: the backend caps a window at a year, and every preset here stays inside it.
const AUTHOR_DATE_OPTIONS = dateMapping.filter(({ key }) =>
    ['Last 7 days', 'Last 14 days', 'Last 30 days', 'Last 90 days', 'Last 180 days', 'This year'].includes(key)
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
    const { handle, sourceId, deliveryScope, workflowCosts, workflowCostsLoading } = useValues(authorLogic)
    const { summary, summaryLoading } = useValues(deliverySummaryLogic({ scope: deliveryScope, sourceId }))
    const { timelines, timelinesLoading, repoSlugs } = useValues(
        pullRequestTimelinesLogic({ scope: deliveryScope, sourceId })
    )
    const { dateFrom, dateTo } = useValues(engineeringAnalyticsFiltersLogic)
    const { setDateRange } = useActions(engineeringAnalyticsFiltersLogic)

    const hubUrl = combineUrl(urls.engineeringAnalytics(), sourceId ? { source: sourceId } : {}).url
    const avatarUrl = timelines?.items[0]?.author.avatar_url
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
                <DeliverySections scope={deliveryScope} scopeLabel="This author" sourceId={sourceId} />

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
        </SceneContent>
    )
}

export default EngineeringAnalyticsAuthorScene
