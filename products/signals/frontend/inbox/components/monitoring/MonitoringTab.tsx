import { useActions, useValues } from 'kea'

import { IconPullRequest } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { monitoringTabLogic } from '../../logics/monitoringTabLogic'
import { pullRequestsLogic } from '../../logics/pullRequestsLogic'
import { captureMonitoringAction } from '../../monitoringAnalytics'
import { useMinuteClock } from '../cards/useMinuteClock'
import { PullRequestsPanel } from '../pullRequests/PullRequestsPanel'
import { MonitoringScopeControl } from './MonitoringScopeControl'
import { MonitoringTimeline } from './MonitoringTimeline'

function PullRequestsToggleButton(): JSX.Element {
    const { panelOpen } = useValues(pullRequestsLogic)
    const { setPanelOpen } = useActions(pullRequestsLogic)
    return (
        <LemonButton
            size="small"
            type="secondary"
            active={panelOpen}
            icon={<IconPullRequest />}
            aria-expanded={panelOpen}
            data-attr="inbox-monitoring-pr-panel-toggle"
            onClick={() => setPanelOpen(!panelOpen)}
        >
            Pull requests
        </LemonButton>
    )
}

function DockedPullRequestsPanel(): JSX.Element | null {
    const { panelOpen } = useValues(pullRequestsLogic)
    return panelOpen ? <PullRequestsPanel className="order-1 @4xl/monitoring:order-none" /> : null
}

export function MonitoringTab(): JSX.Element {
    const prMonitoringEnabled = useFeatureFlag('SIGNALS_MONITOR_PR')
    const { sortedReports, page, pageLoading, loadFailed, scope } = useValues(monitoringTabLogic)
    const { loadReports, loadMore, setScope } = useActions(monitoringTabLogic)
    const now = useMinuteClock(true)

    const content = (
        <div
            className="@container mx-auto flex w-full max-w-6xl flex-col gap-3 px-6 py-4"
            data-attr={prMonitoringEnabled ? undefined : 'inbox-monitoring-tab'}
        >
            <div className="flex flex-wrap items-center justify-end gap-2">
                <MonitoringScopeControl />
                {prMonitoringEnabled ? <PullRequestsToggleButton /> : null}
            </div>
            {loadFailed ? (
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
            ) : page === null ? (
                <LemonSkeleton className="h-64 w-full" />
            ) : sortedReports.length === 0 ? (
                <div className="flex flex-col items-center gap-2 rounded border border-dashed border-primary p-6 text-center text-sm text-secondary">
                    {scope.everyone ? (
                        <span>
                            No fixes are being checked. When a self-driving pull request merges, its report shows up
                            here while PostHog checks that the fix worked.
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
            ) : (
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
            )}
        </div>
    )

    if (!prMonitoringEnabled) {
        return content
    }

    return (
        <div className="@container/monitoring flex h-full min-h-0 w-full min-w-0" data-attr="inbox-monitoring-tab">
            <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col @4xl/monitoring:flex-row @4xl/monitoring:overflow-hidden">
                <div className="order-2 flex min-h-0 min-w-0 flex-1 flex-col @4xl/monitoring:order-none @4xl/monitoring:overflow-y-auto">
                    {content}
                </div>
                <DockedPullRequestsPanel />
            </div>
        </div>
    )
}
