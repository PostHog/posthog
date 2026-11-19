import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { monitoringTabLogic } from '../../logics/monitoringTabLogic'
import { captureMonitoringAction } from '../../monitoringAnalytics'
import { useMinuteClock } from '../cards/useMinuteClock'
import { MonitoringScopeControl } from './MonitoringScopeControl'
import { MonitoringTimeline } from './MonitoringTimeline'

export function MonitoringTab(): JSX.Element {
    const { sortedReports, page, pageLoading, loadFailed, scope } = useValues(monitoringTabLogic)
    const { loadReports, loadMore, setScope } = useActions(monitoringTabLogic)
    const now = useMinuteClock(true)

    return (
        <div className="@container mx-auto flex max-w-6xl flex-col gap-3 px-6 py-4" data-attr="inbox-monitoring-tab">
            <div className="flex justify-end">
                <MonitoringScopeControl />
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
}
