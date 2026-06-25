import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { dateMapping } from 'lib/utils/dateFilters'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { BillableBadge } from '../components/BillableBadge'
import { CIStatusTag } from '../components/CIStatusTag'
import { formatCost, formatMinutes } from '../components/runTables'
import type { PullRequestListItemApi } from '../generated/api.schemas'
import { AuthorLogicProps, authorLogic } from './authorLogic'

// date_from only (the list floors on it); "all time" / week+month snaps are out — open PRs always show.
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

function StatCard({ label, value, sub }: { label: string; value: string; sub: string }): JSX.Element {
    return (
        <div className="flex min-w-44 flex-1 flex-col gap-1 rounded-lg border bg-surface-primary px-5 py-4">
            <span className="text-xs text-secondary">{label}</span>
            <span className="text-2xl leading-none font-semibold tabular-nums">{value}</span>
            <span className="text-xs text-tertiary">{sub}</span>
        </div>
    )
}

export function EngineeringAnalyticsAuthorScene(): JSX.Element {
    const { handle, prs, prsLoading, dateFrom, totalCostUsd, totalBillableMinutes, sourceId } = useValues(authorLogic)
    const { setDateFrom } = useActions(authorLogic)

    const columns: LemonTableColumns<PullRequestListItemApi> = [
        {
            title: 'Pull request',
            key: 'pr',
            render: (_, pr) => (
                <Link
                    to={
                        combineUrl(
                            urls.engineeringAnalyticsPullRequest(pr.repo.owner, pr.repo.name, pr.number),
                            sourceId ? { source: sourceId } : {}
                        ).url
                    }
                    className="font-medium"
                >
                    {pr.title}
                    <span className="ml-1 font-normal text-xs text-secondary">#{pr.number}</span>
                </Link>
            ),
        },
        { title: 'CI', key: 'ci', width: 150, render: (_, pr) => <CIStatusTag rollup={pr.ci} /> },
        {
            title: 'CI cost',
            key: 'cost',
            width: 130,
            align: 'right',
            sorter: (a, b) => (a.estimated_cost_usd ?? -1) - (b.estimated_cost_usd ?? -1),
            render: (_, pr) => <BillableBadge minutes={pr.billable_minutes} costUsd={pr.estimated_cost_usd} />,
        },
        {
            title: 'Opened',
            key: 'opened',
            width: 140,
            align: 'right',
            render: (_, pr) => (
                <span className="text-xs whitespace-nowrap">
                    <TZLabel time={pr.created_at} />
                </span>
            ),
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection name={handle} resourceType={{ type: 'health' }} />
            <div className="flex max-w-5xl flex-col gap-4">
                <DateFilter
                    dateFrom={dateFrom}
                    onChange={(from) => setDateFrom(from ?? '-30d')}
                    dateOptions={AUTHOR_DATE_OPTIONS}
                />
                <div className="flex flex-wrap gap-3">
                    <StatCard
                        label="Pull requests"
                        value={prs.length.toLocaleString()}
                        sub="open + recently finished"
                    />
                    <StatCard
                        label="Billable CI minutes"
                        value={formatMinutes(totalBillableMinutes)}
                        sub={totalCostUsd != null ? `≈ ${formatCost(totalCostUsd)} estimated` : 'no cost data yet'}
                    />
                    <StatCard
                        label="Estimated CI cost"
                        value={formatCost(totalCostUsd)}
                        sub="self-hosted runners only"
                    />
                </div>
                <LemonTable
                    columns={columns}
                    dataSource={prs}
                    loading={prsLoading}
                    rowKey={(pr) => `${pr.repo.owner}/${pr.repo.name}#${pr.number}`}
                    defaultSorting={{ columnKey: 'cost', order: -1 }}
                    emptyState={`No pull requests for ${handle} in this window.`}
                    nouns={['pull request', 'pull requests']}
                />
            </div>
        </SceneContent>
    )
}

export default EngineeringAnalyticsAuthorScene
