import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dateMapping } from 'lib/utils/dateFilters'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PullRequestTable } from '../components/PullRequestTable'
import { formatCost, formatMinutes } from '../components/runTables'
import { StatTile } from '../components/StatTile'
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
    const { handle, prs, prsLoading, windowedRows, totalCostUsd, totalBillableMinutes, sourceId } =
        useValues(authorLogic)
    const { dateFrom, dateTo } = useValues(engineeringAnalyticsFiltersLogic)
    const { setDateRange } = useActions(engineeringAnalyticsFiltersLogic)

    return (
        <SceneContent>
            <SceneTitleSection name={handle} resourceType={{ type: 'health' }} />
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
                    <div className="flex flex-wrap gap-3">
                        <StatTile
                            label="Pull requests opened"
                            value={windowedRows.length.toLocaleString()}
                            sub="in the selected window"
                        />
                        <StatTile
                            label="Billable CI minutes"
                            value={formatMinutes(totalBillableMinutes)}
                            sub={totalCostUsd != null ? `≈ ${formatCost(totalCostUsd)} estimated` : 'no cost data yet'}
                        />
                        <StatTile
                            label="Estimated CI cost"
                            value={formatCost(totalCostUsd)}
                            sub="self-hosted runners; excludes still-running jobs"
                        />
                    </div>
                </div>

                <div className="flex flex-col gap-2">
                    <div className="flex items-baseline gap-2">
                        <h3 className="mb-0">Pull requests</h3>
                        {!prsLoading && <span className="text-xs text-secondary">{pluralize(prs.length, 'PR')}</span>}
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
