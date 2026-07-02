// The authors list — where the unvalued `author: any` lens chip lands. Cohort-level by default;
// author pages exist for finding your own work, not ranking people.

import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonInput, LemonTable, Link } from '@posthog/lemon-ui'

import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { compactUsd } from '../lib/format'
import { authorsListLogic } from './authorsListLogic'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import type { AuthorStatsRow } from './repoOverviewLogic'

export function EngineeringAnalyticsAuthors(): JSX.Element {
    const { authorRows, authorSearch, pullRequestsLoading } = useValues(authorsListLogic)
    const { setAuthorSearch } = useActions(authorsListLogic)
    const { sourceId, notConnected, pullRequests } = useValues(engineeringAnalyticsLogic)

    if (notConnected) {
        return <ConnectGitHubSource />
    }

    const authorUrl = (handle: string): string =>
        combineUrl(urls.engineeringAnalyticsAuthor(handle), sourceId ? { source: sourceId } : {}).url

    return (
        <div className="flex flex-col gap-4">
            <ScopeBar
                repoSlot={<SourceScopeChip />}
                lensFilter={{ label: 'author: any', to: urls.engineeringAnalytics() }}
                showDate={false}
                extra={
                    <LemonInput
                        type="search"
                        size="small"
                        className="w-56"
                        placeholder="Search authors"
                        value={authorSearch}
                        onChange={setAuthorSearch}
                        data-attr="engineering-analytics-author-search"
                    />
                }
            />
            <LemonTable<AuthorStatsRow>
                dataSource={authorRows}
                loading={pullRequestsLoading}
                rowKey={(row) => row.handle}
                useURLForSorting={false}
                columns={[
                    {
                        title: 'Author',
                        key: 'handle',
                        render: (_, row) => (
                            <span className="inline-flex items-center gap-1.5">
                                {row.avatarUrl ? (
                                    <img src={row.avatarUrl} alt="" className="size-5 shrink-0 rounded-full" />
                                ) : (
                                    <Lettermark name={row.handle} />
                                )}
                                <Link to={authorUrl(row.handle)} className="font-medium">
                                    {row.handle}
                                </Link>
                            </span>
                        ),
                    },
                    {
                        title: 'Pull requests',
                        key: 'prCount',
                        align: 'right',
                        sorter: (a, b) => a.prCount - b.prCount,
                        render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.prCount)}</span>,
                    },
                    {
                        title: 'Median open→merge',
                        key: 'median',
                        align: 'right',
                        tooltip: 'Coarse by design: created → merged, draft time included. Merged PRs only.',
                        sorter: (a, b) => (a.medianOpenToMergeSeconds ?? -1) - (b.medianOpenToMergeSeconds ?? -1),
                        render: (_, row) => (
                            <span className="tabular-nums text-xs">
                                {row.medianOpenToMergeSeconds != null
                                    ? humanFriendlyDuration(row.medianOpenToMergeSeconds, { maxUnits: 1 })
                                    : '—'}
                            </span>
                        ),
                    },
                    {
                        title: 'Re-run cycles',
                        key: 'reruns',
                        align: 'right',
                        sorter: (a, b) => a.rerunCycles - b.rerunCycles,
                        render: (_, row) => <span className="tabular-nums text-xs">{row.rerunCycles}</span>,
                    },
                    {
                        title: 'CI cost',
                        key: 'cost',
                        align: 'right',
                        tooltip: 'Estimated CI cost of the workflow runs attributed to their pull requests.',
                        sorter: (a, b) => (a.costUsd ?? -1) - (b.costUsd ?? -1),
                        render: (_, row) => <span className="tabular-nums text-xs">{compactUsd(row.costUsd)}</span>,
                    },
                ]}
                defaultSorting={{ columnKey: 'prCount', order: -1 }}
                pagination={{ pageSize: 50 }}
                emptyState={pullRequestsLoading ? 'Loading…' : 'No authors in the loaded pull requests.'}
                nouns={['author', 'authors']}
            />
            <div className="text-[11px] text-tertiary">
                Derived from the {humanFriendlyNumber(pullRequests.length)} most recent pull requests; bots excluded.
            </div>
        </div>
    )
}
