import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonSwitch,
} from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { PullRequestTable } from '../components/PullRequestTable'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { StatCard } from '../components/StatCard'
import { CIStatusFilter, PRStateFilter, engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'

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
        pullRequestsLoadError,
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

    // A 400 means no GitHub source is connected — prompt to connect. A non-400 failure of this
    // scene's data (cards or the PR list) is shown as a generic, retryable error, never the
    // misleading "connect" state, and never because an endpoint this scene doesn't render failed.
    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (pullRequestsLoadError) {
        return <CIAnalyticsLoadError onRetry={refresh} />
    }

    const failingPct =
        cards && cards.openPrs > 0 ? `${humanFriendlyNumber((cards.failingCi / cards.openPrs) * 100)}% of open` : '—'

    return (
        <div className="flex flex-col gap-4">
            <ScopeBar repoSlot={<SourceScopeChip />} showDate={false} />
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

            <PullRequestTable
                rows={filteredPullRequests}
                loading={pullRequestsLoading}
                sourceId={sourceId}
                costLensEnabled={costLensEnabled}
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
