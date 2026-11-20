import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { pullRequestsLogic, PRMonitoringFilter } from '../../logics/pullRequestsLogic'
import { PullRequestDetail } from './PullRequestDetail'
import { PullRequestRow } from './PullRequestRow'

export function PullRequestsTab(): JSX.Element {
    const { page, pageLoading, listError, filter, selectedUrl } = useValues(pullRequestsLogic)
    const { loadPage, setFilter, selectPR, refresh } = useActions(pullRequestsLogic)
    return (
        <div
            className="grid grid-cols-1 @3xl/inbox:grid-cols-[minmax(15rem,1fr)_3fr] h-full min-h-0 min-w-0"
            data-attr="inbox-pull-requests"
        >
            <aside
                aria-label="Your pull requests"
                className={clsx(
                    'flex-col min-w-0 min-h-0 @3xl/inbox:border-r border-primary',
                    selectedUrl ? 'hidden @3xl/inbox:flex' : 'flex'
                )}
            >
                <div className="p-4 border-b border-primary flex flex-col gap-3">
                    <div className="flex items-center justify-between gap-2">
                        <h2 className="text-sm font-semibold m-0">Your pull requests</h2>
                        <LemonButton
                            icon={<IconRefresh />}
                            size="small"
                            tooltip="Refresh pull requests"
                            aria-label="Refresh pull requests"
                            loading={pageLoading}
                            onClick={refresh}
                        />
                    </div>
                    <LemonSelect<PRMonitoringFilter>
                        value={filter}
                        onChange={setFilter}
                        fullWidth
                        options={[
                            { value: 'all', label: 'All pull requests' },
                            { value: 'monitored', label: 'Monitored' },
                            { value: 'unmonitored', label: 'Unmonitored' },
                        ]}
                    />
                    <span className="text-xs text-secondary">
                        Newest created first{page?.github_login ? ` · @${page.github_login}` : ''}
                    </span>
                </div>
                <div className="overflow-y-auto flex-1 min-h-0">
                    {listError ? (
                        <div className="p-4">
                            <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadPage(null) }}>
                                Could not load your PRs.
                            </LemonBanner>
                        </div>
                    ) : pageLoading && !page ? (
                        <div className="p-4 space-y-4">
                            <LemonSkeleton className="h-20" />
                            <LemonSkeleton className="h-20" />
                            <LemonSkeleton className="h-20" />
                        </div>
                    ) : page && (!page.has_integration || !page.github_login) ? (
                        <div className="p-4 text-secondary">
                            {!page.has_integration ? (
                                <>
                                    <Link to={urls.settings('project-integrations')}>Connect a GitHub integration</Link>{' '}
                                    to browse this project's repositories.
                                </>
                            ) : (
                                <>
                                    <Link to={urls.settings('user-personal-integrations')}>
                                        Connect your GitHub account
                                    </Link>{' '}
                                    so we can find your PRs.
                                </>
                            )}
                        </div>
                    ) : (
                        <>
                            {page?.results.map((pr) => (
                                <PullRequestRow
                                    key={pr.url}
                                    pr={pr}
                                    selected={pr.url === selectedUrl}
                                    onSelect={() => selectPR(pr.url)}
                                />
                            ))}
                            {page && page.results.length === 0 && (
                                <p className="p-4 text-secondary">
                                    {page.next_cursor
                                        ? 'No matching PRs on this page. Load more to keep looking.'
                                        : filter === 'monitored'
                                          ? 'You have not monitored any of your PRs yet.'
                                          : 'No matching pull requests in this project’s connected repositories.'}
                                </p>
                            )}
                        </>
                    )}
                    {page?.next_cursor && !listError && (
                        <div className="p-4">
                            <LemonButton
                                fullWidth
                                type="secondary"
                                loading={pageLoading}
                                onClick={() => loadPage(page.next_cursor)}
                            >
                                Load more
                            </LemonButton>
                        </div>
                    )}
                    {page?.incomplete && (
                        <p className="p-4 text-xs text-secondary">
                            GitHub returned a partial history. Some older PRs may not appear.
                        </p>
                    )}
                </div>
            </aside>
            <PullRequestDetail />
        </div>
    )
}
