import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { Link } from '@posthog/lemon-ui'

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
import { MetricTile } from '../components/MetricTile'
import { PullRequestTable } from '../components/PullRequestTable'
import { formatCost, formatMinutes } from '../components/runTables'
import { RepoScopeChip, ScopeBar } from '../components/ScopeBar'
import { Section, SectionNav } from '../components/Section'
import { ShareRow } from '../components/ShareRow'
import { AuthorLogicProps, authorLogic } from './authorLogic'
import { SHARED_DEFAULT_DATE_FROM, engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'

const SHARE_COLORS = ['var(--brand-blue)', 'var(--success)', 'var(--warning)', 'var(--purple)', 'var(--danger)']

// date_from only (the list floors on it); "all time" / week+month snaps are out. All options are within
// the list's load window so the cost-tile scope is always a subset of the visible PRs.
const AUTHOR_DATE_OPTIONS = dateMapping.filter(({ key }) =>
    ['Custom', 'Last 7 days', 'Last 14 days', 'Last 30 days', 'Last 90 days', 'Last 180 days', 'Year to date'].includes(
        key
    )
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
        openPrCount,
        workflowCosts,
        workflowCostsLoading,
        sourceId,
    } = useValues(authorLogic)
    const { dateFrom, dateTo } = useValues(engineeringAnalyticsFiltersLogic)
    const { setDateRange } = useActions(engineeringAnalyticsFiltersLogic)

    const hubUrl = combineUrl(urls.engineeringAnalytics(), sourceId ? { source: sourceId } : {}).url
    const avatarUrl = prs[0]?.authorAvatarUrl
    const workflowCostsTotal = workflowCosts.reduce((sum, c) => sum + (c.estimated_cost_usd ?? 0), 0)

    return (
        <SceneContent>
            <SceneTitleSection name={handle} resourceType={{ type: 'health' }} />
            <ScopeBar
                repoSlot={
                    <RepoScopeChip
                        label={prs[0] ? `${prs[0].repoOwner}/${prs[0].repoName}` : 'Repository'}
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
                    prsLoading ? undefined : <VerdictPill kind="muted">{pluralize(openPrCount, 'open PR')}</VerdictPill>
                }
            />
            {/* The author page is a way to find and explain one's own work — it lists this author's PRs and
                their CI cost. It carries no per-developer performance/ranking metric (no cycle time, no flaky
                score): the cost figures are transparent spend, not a scoreboard (SPEC §2). */}
            <div className="flex flex-col gap-4">
                {/* The picker scopes the cost tiles only — the PR list below stays the author's recent PRs. */}
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold tracking-wide text-secondary uppercase">CI cost</span>
                        <span className="text-xs text-tertiary">for PRs opened in</span>
                        <DateFilter
                            dateFrom={dateFrom}
                            dateTo={dateTo}
                            onChange={(from, to) => setDateRange(from ?? SHARED_DEFAULT_DATE_FROM, to ?? null)}
                            dateOptions={AUTHOR_DATE_OPTIONS}
                            size="small"
                        />
                    </div>
                    <div className="flex flex-wrap gap-2.5">
                        <MetricTile
                            label="Pull requests opened"
                            value={windowedRows.length.toLocaleString()}
                            sub="in the selected window"
                        />
                        <MetricTile
                            label="CI cost"
                            value={formatCost(totalCostUsd)}
                            sub={
                                totalCostUsd != null
                                    ? `${formatMinutes(totalBillableMinutes)} billable · ${formatCost(
                                          windowedRows.length ? totalCostUsd / windowedRows.length : null
                                      )} per PR`
                                    : 'no cost data yet'
                            }
                        />
                    </div>
                </div>

                <SectionNav
                    items={[
                        { id: 'author-prs', label: 'Pull requests' },
                        { id: 'author-cost', label: 'Cost' },
                    ]}
                />

                <Section
                    id="author-prs"
                    title="Pull requests"
                    note="the shared PR table, filtered to one author"
                    right={
                        !prsLoading ? <span className="text-secondary">{pluralize(prs.length, 'PR')}</span> : undefined
                    }
                >
                    <PullRequestTable
                        rows={prs}
                        loading={prsLoading}
                        sourceId={sourceId}
                        costLensEnabled
                        showAuthor={false}
                        dataAttr="engineering-analytics-author-pr-table"
                        emptyState={`No pull requests for ${handle} in the last year.`}
                    />
                </Section>

                <Section
                    id="author-cost"
                    title="Where their CI minutes go"
                    note="runs attributed via their pull requests, over the window above"
                >
                    {workflowCosts.length > 0 ? (
                        <LemonCard hoverEffect={false} className="p-4 lg:max-w-xl">
                            <h3 className="mb-1 text-xs font-semibold text-secondary">By workflow</h3>
                            {workflowCosts.slice(0, 8).map((cost, i) => (
                                <ShareRow
                                    key={cost.workflow_name || '(unknown)'}
                                    label={cost.workflow_name || '(unknown workflow)'}
                                    sub={`${formatMinutes(cost.billable_minutes)} billable`}
                                    value={formatCost(cost.estimated_cost_usd)}
                                    share={
                                        workflowCostsTotal > 0 ? (cost.estimated_cost_usd ?? 0) / workflowCostsTotal : 0
                                    }
                                    color={SHARE_COLORS[i % SHARE_COLORS.length]}
                                    to={
                                        prs[0]
                                            ? combineUrl(
                                                  urls.engineeringAnalyticsWorkflowRuns(
                                                      prs[0].repoOwner,
                                                      prs[0].repoName,
                                                      cost.workflow_name
                                                  ),
                                                  sourceId ? { source: sourceId } : {}
                                              ).url
                                            : undefined
                                    }
                                />
                            ))}
                        </LemonCard>
                    ) : (
                        <span className="text-xs text-secondary">
                            {workflowCostsLoading
                                ? 'Loading…'
                                : "No cost data — the job-level source isn't synced, or nothing ran in the window."}
                        </span>
                    )}
                </Section>
            </div>
        </SceneContent>
    )
}

export default EngineeringAnalyticsAuthorScene
