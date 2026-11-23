/* eslint-disable react/forbid-dom-props -- Resizer width is user-driven panel state */
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconArrowLeft, IconExternal, IconPullRequest, IconRefresh, IconSidePanel } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTabs, Link } from '@posthog/lemon-ui'

import { Resizer } from 'lib/lemon-ui/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/lemon-ui/Resizer/resizerLogic'
import { urls } from 'scenes/urls'

import { capturePRAction, PRMonitoringFilter, pullRequestsLogic } from '../../logics/pullRequestsLogic'
import { PullRequestDetail } from './PullRequestDetail'
import { PullRequestRow } from './PullRequestRow'

const DEFAULT_PANEL_WIDTH = 380
const MIN_PANEL_WIDTH = 300
const CLOSE_THRESHOLD_WIDTH = 180

function emptyPullRequestsMessage(filter: PRMonitoringFilter, hasNextCursor: boolean): string {
    if (hasNextCursor) {
        return 'No matching pull requests on this page. Load more to keep looking.'
    }
    if (filter === 'monitored') {
        return 'You have not monitored any of your pull requests yet.'
    }
    if (filter === 'unmonitored') {
        return 'All of your recent pull requests are already monitored.'
    }
    return "No matching pull requests in this project's connected repositories."
}

function PullRequestsPanelHeader(): JSX.Element {
    const { page, pageLoading, overviewLoading, selectedUrl, selectedPR } = useValues(pullRequestsLogic)
    const { selectPR, refresh, setPanelOpen } = useActions(pullRequestsLogic)

    return (
        <div className="flex h-9 shrink-0 items-center justify-between gap-1 border-b border-primary bg-surface-primary pl-2.5 pr-1.5">
            {selectedUrl ? (
                <div className="flex min-w-0 items-center gap-1">
                    <LemonButton
                        icon={<IconArrowLeft />}
                        size="xsmall"
                        type="tertiary"
                        data-attr="inbox-pr-back"
                        onClick={() => selectPR(null)}
                    >
                        Pull requests
                    </LemonButton>
                    {selectedPR ? (
                        <span className="truncate font-mono text-xs text-tertiary">#{selectedPR.number}</span>
                    ) : null}
                </div>
            ) : (
                <div className="flex min-w-0 items-center gap-1.5 pl-0.5">
                    <IconPullRequest className="size-3.5 shrink-0 text-secondary" />
                    <h2 className="m-0 truncate text-xs font-semibold text-primary">Pull requests</h2>
                    {page?.github_login ? (
                        <span className="truncate text-xs text-tertiary">@{page.github_login}</span>
                    ) : null}
                </div>
            )}
            <div className="flex shrink-0 items-center gap-0.5">
                {selectedPR ? (
                    <LemonButton
                        icon={<IconExternal />}
                        size="xsmall"
                        type="tertiary"
                        to={selectedPR.url}
                        targetBlank
                        tooltip="Open on GitHub"
                        aria-label="Open on GitHub"
                        data-attr="inbox-pr-open-github"
                        onClick={() => capturePRAction('open_github')}
                    />
                ) : null}
                <LemonButton
                    icon={<IconRefresh />}
                    size="xsmall"
                    type="tertiary"
                    tooltip="Refresh pull requests"
                    aria-label="Refresh pull requests"
                    data-attr="inbox-pr-refresh"
                    loading={Boolean(selectedUrl ? overviewLoading : pageLoading)}
                    onClick={refresh}
                />
                <LemonButton
                    icon={<IconSidePanel />}
                    size="xsmall"
                    type="tertiary"
                    tooltip="Collapse panel"
                    aria-label="Collapse pull requests panel"
                    data-attr="inbox-pr-panel-collapse"
                    onClick={() => setPanelOpen(false)}
                />
            </div>
        </div>
    )
}

function PullRequestsSetupNotice({ hasIntegration }: { hasIntegration: boolean }): JSX.Element {
    return (
        <div className="p-3.5 text-xs text-secondary">
            {!hasIntegration ? (
                <>
                    <Link to={urls.settings('project-integrations')}>Connect a GitHub integration</Link> to browse this
                    project's repositories.
                </>
            ) : (
                <>
                    <Link to={urls.settings('user-personal-integrations')}>Connect your GitHub account</Link> so we can
                    find your pull requests.
                </>
            )}
        </div>
    )
}

function PullRequestsListFooter(): JSX.Element {
    const { page, pageLoading, listError } = useValues(pullRequestsLogic)
    const { loadPullRequests } = useActions(pullRequestsLogic)

    if (!page) {
        return <></>
    }

    return (
        <>
            {listError ? (
                <div className="p-3">
                    <LemonBanner type="error" action={{ children: 'Refresh', onClick: () => loadPullRequests(null) }}>
                        Could not load more pull requests. Refresh to reload the list.
                    </LemonBanner>
                </div>
            ) : page.next_cursor ? (
                <div className="p-2.5">
                    <LemonButton
                        fullWidth
                        size="small"
                        type="secondary"
                        data-attr="inbox-pr-load-more"
                        loading={pageLoading}
                        onClick={() => loadPullRequests(page.next_cursor)}
                    >
                        Load more
                    </LemonButton>
                </div>
            ) : null}
            {page.incomplete ? (
                <p className="m-0 px-3 pb-3 text-[11px] text-tertiary">
                    GitHub returned a partial history. Some older pull requests may not appear.
                </p>
            ) : null}
        </>
    )
}

function PullRequestsListBody(): JSX.Element {
    const { page, pageLoading, listError, filter } = useValues(pullRequestsLogic)
    const { loadPullRequests, selectPR } = useActions(pullRequestsLogic)

    if (!page && listError) {
        return (
            <div className="p-3">
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadPullRequests(null) }}>
                    Could not load your pull requests.
                </LemonBanner>
            </div>
        )
    }

    if (!page && pageLoading) {
        return (
            <div className="divide-y divide-border">
                <div className="p-3">
                    <LemonSkeleton className="h-10" />
                </div>
                <div className="p-3">
                    <LemonSkeleton className="h-10" />
                </div>
                <div className="p-3">
                    <LemonSkeleton className="h-10" />
                </div>
            </div>
        )
    }

    if (!page) {
        return <></>
    }

    if (!page.has_integration || !page.github_login) {
        return <PullRequestsSetupNotice hasIntegration={page.has_integration} />
    }

    return (
        <>
            {page.results.map((pr) => (
                <PullRequestRow key={pr.url} pr={pr} onSelect={() => selectPR(pr.url)} />
            ))}
            {page.results.length === 0 ? (
                <p className="m-0 p-3.5 text-xs text-secondary">
                    {emptyPullRequestsMessage(filter, Boolean(page.next_cursor))}
                </p>
            ) : null}
            <PullRequestsListFooter />
        </>
    )
}

export function PullRequestsPanel({ className }: { className?: string }): JSX.Element {
    const panelRef = useRef<HTMLDivElement>(null)
    const { filter, selectedUrl } = useValues(pullRequestsLogic)
    const { setFilter, setPanelOpen } = useActions(pullRequestsLogic)

    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'inbox-monitoring-pr-panel',
        containerRef: panelRef,
        persistent: true,
        persistPrefix: '2026-11-20',
        placement: 'left',
        closeThreshold: CLOSE_THRESHOLD_WIDTH,
        onToggleClosed: (shouldBeClosed) => setPanelOpen(!shouldBeClosed),
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <div
            ref={panelRef}
            role="complementary"
            aria-label="Pull requests"
            data-attr="inbox-pr-panel"
            style={{
                width: desiredSize ?? DEFAULT_PANEL_WIDTH,
                minWidth: MIN_PANEL_WIDTH,
                maxWidth: '48%',
            }}
            className={clsx(
                'relative flex min-h-0 shrink-0 flex-col overflow-hidden border-l border-primary bg-surface-primary h-full @max-[56rem]/monitoring:h-auto @max-[56rem]/monitoring:max-h-[26rem] @max-[56rem]/monitoring:!w-full @max-[56rem]/monitoring:!min-w-0 @max-[56rem]/monitoring:!max-w-full @max-[56rem]/monitoring:border-b @max-[56rem]/monitoring:border-l-0',
                className
            )}
        >
            <Resizer {...resizerLogicProps} offset={0} className="hidden @4xl/monitoring:block" />
            <PullRequestsPanelHeader />

            {selectedUrl ? (
                <div className="min-h-0 flex-1 overflow-y-auto">
                    <PullRequestDetail />
                </div>
            ) : (
                <>
                    <div className="shrink-0 border-b border-primary bg-surface-primary px-3">
                        <LemonTabs<PRMonitoringFilter>
                            size="small"
                            activeKey={filter}
                            onChange={setFilter}
                            barClassName="before:hidden !mb-0"
                            data-attr="inbox-pr-filter-tabs"
                            tabs={[
                                { key: 'all', label: 'All', 'data-attr': 'inbox-pr-filter-all' },
                                {
                                    key: 'unmonitored',
                                    label: 'Unmonitored',
                                    'data-attr': 'inbox-pr-filter-unmonitored',
                                },
                                { key: 'monitored', label: 'Monitored', 'data-attr': 'inbox-pr-filter-monitored' },
                            ]}
                        />
                    </div>
                    <div className="min-h-0 flex-1 overflow-y-auto">
                        <PullRequestsListBody />
                    </div>
                </>
            )}
        </div>
    )
}
