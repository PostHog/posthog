import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonSwitch,
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

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
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
        stateFilter,
        author,
        repo,
        ciStatusFilter,
        search,
        authorOptions,
        repoOptions,
        hasActiveFilters,
        activeCard,
        sourceId,
        notConnected,
        loadError,
        costLensEnabled,
    } = useValues(engineeringAnalyticsLogic)
    const {
        setStateFilter,
        setAuthor,
        setRepo,
        setCiStatusFilter,
        setSearch,
        resetFilters,
        applyCardFilter,
        setCostLensEnabled,
        refresh,
    } = useActions(engineeringAnalyticsLogic)

    // A 400 means no GitHub source is connected — prompt to connect. Any other failure (e.g. a 500
    // from a query error) is shown as a generic, retryable error, never the misleading "connect" state.
    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (loadError) {
        return <CIAnalyticsLoadError onRetry={refresh} />
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
        // Cost & performance lens: friction signals available today (pushes / re-runs) plus the cost
        // scaffold ("pending" until the job-level warehouse source lands).
        ...(costLensEnabled
            ? ([
                  {
                      title: 'Pushes',
                      key: 'pushes',
                      width: 90,
                      align: 'right',
                      tooltip:
                          'CI triggers in the PR window: distinct head commits that ran CI. Fork PRs are unattributed.',
                      sorter: (a, b) => a.pushes - b.pushes,
                      render: (_, row) => (
                          <span className="text-xs tabular-nums">{humanFriendlyNumber(row.pushes)}</span>
                      ),
                  },
                  {
                      title: 'Re-runs',
                      key: 'rerunCycles',
                      width: 90,
                      align: 'right',
                      tooltip: 'Workflow runs on this PR that were a 2nd+ attempt (a re-run).',
                      sorter: (a, b) => a.rerunCycles - b.rerunCycles,
                      render: (_, row) => (
                          <span className="text-xs tabular-nums">
                              {row.rerunCycles > 0 ? humanFriendlyNumber(row.rerunCycles) : '—'}
                          </span>
                      ),
                  },
                  {
                      title: 'Est. cost',
                      key: 'estimatedCostUsd',
                      width: 110,
                      align: 'right',
                      tooltip: 'Estimated Depot CI cost. Lands with job-level CI data — not available yet.',
                      render: (_, row) =>
                          row.estimatedCostUsd == null ? (
                              <LemonTag type="muted">pending</LemonTag>
                          ) : (
                              <span className="text-xs tabular-nums">${humanFriendlyNumber(row.estimatedCostUsd)}</span>
                          ),
                  },
              ] as LemonTableColumns<PullRequestRow>)
            : []),
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
                <LemonSwitch
                    label="Cost & performance lens"
                    checked={costLensEnabled}
                    onChange={setCostLensEnabled}
                    size="small"
                    bordered
                    data-attr="engineering-analytics-cost-lens"
                />
            </div>

            <LemonTable
                data-attr="engineering-analytics-pr-table"
                size="small"
                columns={columns}
                dataSource={filteredPullRequests}
                rowKey={prKeyOf}
                loading={pullRequestsLoading}
                onRow={(row) => {
                    // Carry the selected source so the PR's detail page reads the same one.
                    const detailUrl = combineUrl(
                        urls.engineeringAnalyticsPullRequest(row.repoOwner, row.repoName, row.number),
                        sourceId ? { source: sourceId } : {}
                    ).url
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
