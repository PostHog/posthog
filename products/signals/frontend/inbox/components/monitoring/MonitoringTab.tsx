import { useActions, useValues } from 'kea'

import { IconPullRequest, IconSidePanel } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { monitoringTabLogic } from '../../logics/monitoringTabLogic'
import { pullRequestsLogic } from '../../logics/pullRequestsLogic'
import { captureMonitoringAction } from '../../monitoringAnalytics'
import { useMinuteClock } from '../cards/useMinuteClock'
import { PullRequestsPanel } from '../pullRequests/PullRequestsPanel'
import { MonitoringScopeControl } from './MonitoringScopeControl'
import { MonitoringTimeline } from './MonitoringTimeline'

function MonitoringTimelineSection({ now }: { now: number }): JSX.Element {
    const { sortedReports, page, pageLoading, loadFailed, scope } = useValues(monitoringTabLogic)
    const { loadReports, loadMore, setScope } = useActions(monitoringTabLogic)

    if (loadFailed) {
        return (
            <div className="flex flex-col items-center gap-2 rounded border border-primary p-6 text-center text-sm">
                <span>
                    Couldn't load the fixes being checked. Try again, and if it keeps happening, refresh the page.
                </span>
                <LemonButton
                    size="small"
                    type="secondary"
                    data-attr="inbox-monitoring-retry"
                    onClick={() => {
                        captureMonitoringAction({ action: 'retry' })
                        loadReports()
                    }}
                >
                    Try again
                </LemonButton>
            </div>
        )
    }

    if (page === null) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    if (sortedReports.length === 0) {
        return (
            <div className="flex flex-col items-center gap-2 rounded border border-dashed border-primary p-6 text-center text-sm text-secondary">
                {scope.everyone ? (
                    <span>
                        No fixes are being checked. When a self-driving pull request merges, its report shows up here
                        while PostHog checks that the fix worked.
                    </span>
                ) : (
                    <>
                        <span>No fixes for you are being checked or finished in the last 14 days.</span>
                        <LemonButton
                            size="small"
                            type="secondary"
                            data-attr="inbox-monitoring-show-everyone"
                            onClick={() => {
                                captureMonitoringAction({ action: 'show_everyone' })
                                setScope({ ...scope, everyone: true })
                            }}
                        >
                            Show everyone's
                        </LemonButton>
                    </>
                )}
            </div>
        )
    }

    return (
        <>
            <MonitoringTimeline reports={sortedReports} now={now} />
            {page.hasMore ? (
                <div className="flex justify-center">
                    <LemonButton
                        size="small"
                        type="secondary"
                        loading={pageLoading}
                        onClick={() => {
                            captureMonitoringAction({ action: 'load_more' })
                            loadMore()
                        }}
                        data-attr="inbox-monitoring-load-more"
                    >
                        Load more
                    </LemonButton>
                </div>
            ) : null}
        </>
    )
}

function CollapsedPullRequestsRail({ onOpen }: { onOpen: () => void }): JSX.Element {
    return (
        <aside
            aria-label="Pull requests panel collapsed"
            className="hidden h-full w-9 shrink-0 flex-col items-center border-l border-primary bg-surface-primary py-1.5 @4xl/monitoring:flex"
        >
            <Tooltip title="Open pull requests panel" placement="left">
                <button
                    type="button"
                    onClick={onOpen}
                    aria-label="Open pull requests panel"
                    data-attr="inbox-monitoring-pr-panel-toggle"
                    className="group flex cursor-pointer flex-col items-center gap-2.5 rounded px-1.5 py-2 text-tertiary transition-colors hover:bg-fill-highlight-50 hover:text-primary focus-visible:outline focus-visible:outline-accent"
                >
                    <IconSidePanel className="size-4 shrink-0" />
                    <IconPullRequest className="size-3.5 shrink-0" />
                    <span className="select-none text-[11px] font-medium tracking-wide [writing-mode:vertical-rl]">
                        Pull requests
                    </span>
                </button>
            </Tooltip>
        </aside>
    )
}

function MonitoringTabWithPullRequests({ now }: { now: number }): JSX.Element {
    const { panelOpen } = useValues(pullRequestsLogic)
    const { setPanelOpen, togglePanel } = useActions(pullRequestsLogic)

    return (
        <div className="@container/monitoring flex h-full min-h-0 w-full min-w-0" data-attr="inbox-monitoring-tab">
            <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col @4xl/monitoring:flex-row @4xl/monitoring:overflow-hidden">
                <div className="order-2 flex min-h-0 min-w-0 flex-1 flex-col @4xl/monitoring:order-none @4xl/monitoring:overflow-y-auto">
                    <div className="@container mx-auto flex w-full max-w-6xl flex-col gap-3 px-6 py-4">
                        <div className="flex flex-wrap items-center justify-end gap-2">
                            <MonitoringScopeControl />
                            <div className="@4xl/monitoring:hidden">
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    active={panelOpen}
                                    icon={<IconPullRequest />}
                                    aria-expanded={panelOpen}
                                    data-attr="inbox-monitoring-pr-panel-toggle-compact"
                                    onClick={togglePanel}
                                >
                                    Pull requests
                                </LemonButton>
                            </div>
                        </div>
                        <MonitoringTimelineSection now={now} />
                    </div>
                </div>

                {panelOpen ? (
                    <PullRequestsPanel className="order-1 @4xl/monitoring:order-none" />
                ) : (
                    <CollapsedPullRequestsRail onOpen={() => setPanelOpen(true)} />
                )}
            </div>
        </div>
    )
}

export function MonitoringTab(): JSX.Element {
    const prMonitoringEnabled = useFeatureFlag('SIGNALS_MONITOR_PR')
    const now = useMinuteClock(true)

    if (prMonitoringEnabled) {
        return <MonitoringTabWithPullRequests now={now} />
    }

    return (
        <div className="@container mx-auto flex max-w-6xl flex-col gap-3 px-6 py-4" data-attr="inbox-monitoring-tab">
            <div className="flex justify-end">
                <MonitoringScopeControl />
            </div>
            <MonitoringTimelineSection now={now} />
        </div>
    )
}
