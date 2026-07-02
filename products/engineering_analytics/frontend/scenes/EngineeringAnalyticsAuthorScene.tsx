import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { Link } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
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
import { compactHours, compactHoursUnit } from '../lib/format'
import { AuthorLogicProps, authorLogic } from './authorLogic'
import { SHARED_DEFAULT_DATE_FROM, engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'

// date_from only (the list floors on it); "all time" / week+month snaps are out. All options are within
// the list's load window so the tile scope is always a subset of the visible PRs.
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
        medianOpenToMergeSeconds,
        rerunCycles,
        openPrCount,
        sourceId,
    } = useValues(authorLogic)
    const { dateFrom, dateTo } = useValues(engineeringAnalyticsFiltersLogic)
    const { setDateRange } = useActions(engineeringAnalyticsFiltersLogic)

    const hubUrl = combineUrl(urls.engineeringAnalytics(), sourceId ? { source: sourceId } : {}).url
    const avatarUrl = prs[0]?.authorAvatarUrl

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
            <div className="flex flex-col gap-4">
                {/* The picker scopes the tiles only — the PR list below stays the author's recent PRs. */}
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold tracking-wide text-secondary uppercase">Stats</span>
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
                            label="Median open → merge"
                            value={compactHours(medianOpenToMergeSeconds)}
                            valueSuffix={compactHoursUnit(medianOpenToMergeSeconds)}
                            sub="merged PRs in the window; coarse — draft time included"
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
                        <MetricTile
                            label="Re-run cycles"
                            value={rerunCycles.toLocaleString()}
                            sub={rerunCycles > 8 ? 'high — often a flaky-test signal' : 'in the normal band'}
                        />
                    </div>
                </div>

                <div className="flex flex-col gap-2">
                    <div className="flex items-baseline gap-2">
                        <h3 className="mb-0">Pull requests</h3>
                        {!prsLoading && <span className="text-xs text-secondary">{pluralize(prs.length, 'PR')}</span>}
                        <span className="text-xs text-tertiary">
                            same table as the repo overview — one component, scoped to one author
                        </span>
                    </div>
                    <PullRequestTable
                        rows={prs}
                        loading={prsLoading}
                        sourceId={sourceId}
                        costLensEnabled
                        showAuthor={false}
                        defaultSorting={{ columnKey: 'age', order: -1 }}
                        dataAttr="engineering-analytics-author-pr-table"
                        emptyState={`No pull requests for ${handle} in the last year.`}
                    />
                </div>
            </div>
        </SceneContent>
    )
}

export default EngineeringAnalyticsAuthorScene
