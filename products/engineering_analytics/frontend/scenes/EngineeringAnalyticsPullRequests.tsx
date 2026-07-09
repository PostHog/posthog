import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { RepoEntityHeader } from '../components/EntityHeader'
import { PullRequestTable } from '../components/PullRequestTable'
import { SourceScopeChip } from '../components/ScopeBar'
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
        ciStatusFilter,
        search,
        hasActiveFilters,
        activeCard,
        sourceId,
        activeSource,
        notConnected,
        pullRequestsLoadError,
    } = useValues(engineeringAnalyticsLogic)
    const { setStateFilter, setCiStatusFilter, setSearch, resetFilters, applyCardFilter, refresh } =
        useActions(engineeringAnalyticsLogic)

    // A 400 means no GitHub source — prompt to connect. A non-400 failure of this scene's data (cards or
    // the PR list) shows a retryable error, never the misleading "connect" state.
    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (pullRequestsLoadError) {
        return <CIAnalyticsLoadError onRetry={refresh} />
    }

    const failingPct =
        cards && cards.openPrs > 0 ? `${Math.round((cards.failingCi / cards.openPrs) * 100)}% of open` : undefined

    return (
        <div className="flex flex-col gap-4">
            <RepoEntityHeader repoFullName={activeSource?.repo || ''} right={<SourceScopeChip pickerOnly />} />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <StatCard
                    label="Open PRs"
                    value={cards ? humanFriendlyNumber(cards.openPrs) : '—'}
                    loading={cardsLoading}
                    onClick={() => applyCardFilter('open')}
                    active={activeCard === 'open'}
                    filterHint="Filter the list to open PRs"
                />
                <StatCard
                    label="Failing CI"
                    value={cards ? humanFriendlyNumber(cards.failingCi) : '—'}
                    caption={failingPct}
                    loading={cardsLoading}
                    onClick={() => applyCardFilter('failing')}
                    active={activeCard === 'failing'}
                    filterHint="Filter the list to open PRs with failing CI"
                />
                <StatCard
                    label="Stuck > 7d"
                    value={cards ? humanFriendlyNumber(cards.stuck) : '—'}
                    caption="excludes drafts and bots"
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
                    className="w-80"
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
            </div>

            <PullRequestTable
                rows={filteredPullRequests}
                loading={pullRequestsLoading}
                sourceId={sourceId}
                costLensEnabled
                showCreated
                emptyState={
                    hasActiveFilters ? (
                        <div className="flex flex-col items-center gap-2">
                            <span>No pull requests match these filters.</span>
                            <LemonButton type="secondary" size="small" onClick={resetFilters}>
                                Clear filters
                            </LemonButton>
                        </div>
                    ) : (
                        "No pull requests yet. They'll appear once the GitHub source syncs."
                    )
                }
            />

            {tableTruncated && <div className="text-xs text-tertiary">Showing the most recent 1000 pull requests.</div>}
        </div>
    )
}
