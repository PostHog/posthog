import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration, humanFriendlyNumber } from 'lib/utils'

import { CIStatusTag } from '../components/CIStatusTag'
import { StatCard } from '../components/StatCard'
import { CIStatusFilter, PRStateFilter, PullRequestRow, engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'

function githubPrUrl(row: PullRequestRow): string {
    return `https://github.com/${row.repoOwner}/${row.repoName}/pull/${row.number}`
}

export function EngineeringAnalyticsPullRequests(): JSX.Element {
    const {
        cards,
        cardsLoading,
        filteredPullRequests,
        pullRequestsLoading,
        tableTruncated,
        loadFailed,
        stateFilter,
        author,
        repo,
        ciStatusFilter,
        search,
        authorOptions,
        repoOptions,
    } = useValues(engineeringAnalyticsLogic)
    const { setStateFilter, setAuthor, setRepo, setCiStatusFilter, setSearch } = useActions(engineeringAnalyticsLogic)

    if (loadFailed) {
        return (
            <LemonBanner type="warning">
                Couldn't load engineering analytics. This scene reads two HogQL views over GitHub warehouse data —
                connect a GitHub data warehouse source to this project to populate it.
            </LemonBanner>
        )
    }

    const failingPct =
        cards && cards.openPrs > 0 ? `${humanFriendlyNumber((cards.failingCi / cards.openPrs) * 100)}% of open` : '—'

    const columns: LemonTableColumns<PullRequestRow> = [
        {
            title: 'Pull request',
            key: 'title',
            render: (_, row) => (
                <div className="flex flex-col gap-0.5">
                    <Link to={githubPrUrl(row)} target="_blank" className="font-medium">
                        {row.title}
                    </Link>
                    <div className="flex items-center gap-1.5 text-xs text-secondary">
                        <span className="font-mono">
                            {row.repoOwner}/{row.repoName} #{row.number}
                        </span>
                        {row.isDraft && <LemonTag type="muted">draft</LemonTag>}
                        {row.labels.slice(0, 3).map((label) => (
                            <LemonTag key={label} type="option">
                                {label}
                            </LemonTag>
                        ))}
                    </div>
                </div>
            ),
        },
        {
            title: 'CI',
            key: 'ci',
            render: (_, row) => <CIStatusTag rollup={row} />,
        },
        {
            title: 'Author',
            key: 'author',
            render: (_, row) => (
                <div className="flex items-center gap-1.5">
                    {row.authorAvatarUrl && (
                        <img src={row.authorAvatarUrl} alt="" className="h-5 w-5 shrink-0 rounded-full" />
                    )}
                    <span className="text-xs">{row.authorHandle}</span>
                    {row.isBot && <LemonTag type="muted">bot</LemonTag>}
                </div>
            ),
        },
        {
            title: 'Age',
            key: 'age',
            align: 'right',
            sorter: (a, b) => dayjs(a.createdAt).valueOf() - dayjs(b.createdAt).valueOf(),
            render: (_, row) => (
                <Tooltip title={dayjs(row.createdAt).format('YYYY-MM-DD HH:mm')}>
                    <span className="text-xs whitespace-nowrap">{dayjs(row.createdAt).fromNow(true)}</span>
                </Tooltip>
            ),
        },
        {
            title: 'Open→merge',
            key: 'openToMerge',
            align: 'right',
            sorter: (a, b) => (a.openToMergeSeconds ?? -1) - (b.openToMergeSeconds ?? -1),
            render: (_, row) => (
                <span className="text-xs whitespace-nowrap text-secondary">
                    {row.openToMergeSeconds == null ? '—' : humanFriendlyDuration(row.openToMergeSeconds)}
                </span>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <StatCard
                    label="Open PRs"
                    value={cards ? humanFriendlyNumber(cards.openPrs) : '—'}
                    caption={cards ? `across ${humanFriendlyNumber(cards.repos)} repos` : ' '}
                    loading={cardsLoading}
                />
                <StatCard
                    label="Failing CI"
                    value={cards ? humanFriendlyNumber(cards.failingCi) : '—'}
                    caption={`${failingPct} · workflow-level`}
                    loading={cardsLoading}
                />
                <StatCard
                    label="Stuck > 7d"
                    value={cards ? humanFriendlyNumber(cards.stuck) : '—'}
                    caption="open > 7d, not draft, not bot"
                    loading={cardsLoading}
                />
            </div>

            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search title, repo, author, #id…"
                    value={search}
                    onChange={setSearch}
                    className="w-64"
                />
                <LemonSegmentedButton
                    size="small"
                    value={stateFilter}
                    onChange={(value) => setStateFilter(value as PRStateFilter)}
                    options={[
                        { value: 'open', label: 'Open' },
                        { value: 'merged', label: 'Merged' },
                        { value: 'all', label: 'All' },
                    ]}
                />
                <LemonSelect
                    size="small"
                    value={ciStatusFilter}
                    onChange={(value) => setCiStatusFilter(value as CIStatusFilter)}
                    options={[
                        { value: 'all', label: 'CI: any' },
                        { value: 'passing', label: 'CI: passing' },
                        { value: 'failing', label: 'CI: failing' },
                        { value: 'running', label: 'CI: running' },
                        { value: 'none', label: 'CI: none' },
                    ]}
                />
                <LemonSelect
                    size="small"
                    placeholder="Repo: all"
                    value={repo}
                    onChange={setRepo}
                    allowClear
                    options={repoOptions.map((r) => ({ value: r, label: r }))}
                />
                <LemonSelect
                    size="small"
                    placeholder="Author: anyone"
                    value={author}
                    onChange={setAuthor}
                    allowClear
                    options={authorOptions.map((a) => ({ value: a, label: a }))}
                />
            </div>

            <LemonTable
                data-attr="engineering-analytics-pr-table"
                size="small"
                columns={columns}
                dataSource={filteredPullRequests}
                rowKey={(row) => `${row.repoOwner}/${row.repoName}#${row.number}`}
                loading={pullRequestsLoading && filteredPullRequests.length === 0}
                useURLForSorting={false}
                emptyState="No pull requests match these filters."
                nouns={['pull request', 'pull requests']}
            />

            <div className="text-[11px] text-tertiary">
                CI is a workflow-level rollup via the head-commit join, not per-check — a run that hasn't completed
                shows as Running, not a pass or fail. "Open→merge" is created-to-merged time (merged PRs only), never
                review or cycle time.
                {tableTruncated && ' Showing the most recent 1000 PRs.'}
            </div>
        </div>
    )
}
