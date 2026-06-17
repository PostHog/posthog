import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { CIStatusTag } from '../components/CIStatusTag'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { StatCard } from '../components/StatCard'
import { githubPrUrl } from '../lib/github'
import {
    CIStatusFilter,
    PRStateFilter,
    PullRequestRow,
    engineeringAnalyticsLogic,
    prKeyOf,
} from './engineeringAnalyticsLogic'

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
        hasActiveFilters,
        activeCard,
    } = useValues(engineeringAnalyticsLogic)
    const { setStateFilter, setAuthor, setRepo, setCiStatusFilter, setSearch, resetFilters, applyCardFilter } =
        useActions(engineeringAnalyticsLogic)

    if (loadFailed) {
        return <ConnectGitHubSource />
    }

    const failingPct =
        cards && cards.openPrs > 0 ? `${humanFriendlyNumber((cards.failingCi / cards.openPrs) * 100)}% of open` : '—'

    const columns: LemonTableColumns<PullRequestRow> = [
        {
            title: 'Pull request',
            key: 'title',
            render: (_, row) => (
                <div className="flex flex-col gap-0.5">
                    <Link
                        to={githubPrUrl(row.repoOwner, row.repoName, row.number)}
                        target="_blank"
                        className="font-medium"
                    >
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
            width: 190,
            render: (_, row) => <CIStatusTag rollup={row} />,
        },
        {
            title: 'Author',
            key: 'author',
            width: 190,
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
            title: 'Opened',
            key: 'age',
            width: 130,
            align: 'right',
            sorter: (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime(),
            render: (_, row) => (
                <span className="text-xs whitespace-nowrap">
                    <TZLabel time={row.createdAt} />
                </span>
            ),
        },
        {
            title: 'Open→merge',
            key: 'openToMerge',
            width: 130,
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
                    caption={cards ? `across ${pluralize(cards.repos, 'repo')}` : ' '}
                    loading={cardsLoading}
                    onClick={() => applyCardFilter('open')}
                    active={activeCard === 'open'}
                    filterHint="Filter the list to open PRs"
                />
                <StatCard
                    label="Failing CI"
                    value={cards ? humanFriendlyNumber(cards.failingCi) : '—'}
                    caption={`${failingPct} · workflow-level`}
                    loading={cardsLoading}
                    onClick={() => applyCardFilter('failing')}
                    active={activeCard === 'failing'}
                    filterHint="Filter the list to open PRs with failing CI"
                />
                <StatCard
                    label="Stuck > 7d"
                    value={cards ? humanFriendlyNumber(cards.stuck) : '—'}
                    caption="open > 7d, not draft, not bot"
                    loading={cardsLoading}
                    onClick={() => applyCardFilter('stuck')}
                    active={activeCard === 'stuck'}
                    filterHint="Filter the list to PRs stuck open for over 7 days"
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
                <LemonSelect
                    size="small"
                    placeholder="Repo: all"
                    value={repo}
                    onChange={setRepo}
                    allowClear
                    options={repoOptions.map((r) => ({ value: r, label: r }))}
                />
                <div className="w-48">
                    <LemonInputSelect
                        mode="single"
                        size="small"
                        placeholder="Author: anyone"
                        value={author ? [author] : []}
                        onChange={(values) => setAuthor(values[0] ?? null)}
                        options={authorOptions.map((a) => ({ key: a, label: a }))}
                        data-attr="engineering-analytics-author-filter"
                    />
                </div>
            </div>

            <LemonTable
                data-attr="engineering-analytics-pr-table"
                size="small"
                columns={columns}
                dataSource={filteredPullRequests}
                rowKey={prKeyOf}
                loading={pullRequestsLoading}
                onRow={(row) => {
                    const detailUrl = urls.engineeringAnalyticsPullRequest(row.repoOwner, row.repoName, row.number)
                    return {
                        // Inner links (PR title → GitHub) keep their own behavior.
                        onClick: (e: React.MouseEvent) => {
                            if ((e.target as HTMLElement).closest('a, button')) {
                                return
                            }
                            if (e.metaKey || e.ctrlKey) {
                                e.preventDefault()
                                newInternalTab(detailUrl)
                            } else {
                                router.actions.push(detailUrl)
                            }
                        },
                        onAuxClick: (e: React.MouseEvent) => {
                            if (e.button === 1 && !(e.target as HTMLElement).closest('a, button')) {
                                e.preventDefault()
                                newInternalTab(detailUrl)
                            }
                        },
                    }
                }}
                useURLForSorting={false}
                pagination={{ pageSize: 50 }}
                emptyState={
                    hasActiveFilters ? (
                        <div className="flex flex-col items-center gap-2">
                            <span>No pull requests match these filters.</span>
                            <LemonButton type="secondary" size="small" onClick={resetFilters}>
                                Clear filters
                            </LemonButton>
                        </div>
                    ) : (
                        'No pull requests yet — they show up as soon as CI events arrive.'
                    )
                }
                nouns={['pull request', 'pull requests']}
            />

            <div className="text-xs text-tertiary">
                CI is a workflow-level rollup via the head-commit join, not per-check — a run that hasn't completed
                shows as Running, not a pass or fail. "Open→merge" is created-to-merged time (merged PRs only), never
                review or cycle time.
                {tableTruncated && ' Showing the most recent 1000 PRs.'}
            </div>
        </div>
    )
}
