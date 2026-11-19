import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { monitoringTabLogic } from '../../logics/monitoringTabLogic'
import { verdictsDueWithin } from '../../utils/monitoringTimeline'
import { useMinuteClock } from '../cards/useMinuteClock'
import { MonitoringScopeControl } from './MonitoringScopeControl'
import { MonitoringTimeline } from './MonitoringTimeline'

const DAY_MS = 86_400_000

function plural(count: number, one: string, many: string): string {
    return `${count} ${count === 1 ? one : many}`
}

export function MonitoringTab(): JSX.Element {
    const { sortedReports, page, pageLoading, loadFailed, scope } = useValues(monitoringTabLogic)
    const { loadReports, loadMore, setScope } = useActions(monitoringTabLogic)
    const now = useMinuteClock(true)
    const beingChecked = sortedReports.filter((report) => !report.monitoring_outcome).length
    const dueSoon = verdictsDueWithin(sortedReports, now, DAY_MS)

    return (
        <div className="@container mx-auto flex max-w-6xl flex-col gap-3 px-6 py-4" data-attr="inbox-monitoring-tab">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm text-secondary">
                    {page ? (
                        <>
                            <span className="font-semibold text-primary">
                                {plural(dueSoon, 'verdict', 'verdicts')} in the next 24 hours
                            </span>
                            {' · '}
                            {plural(beingChecked, 'fix', 'fixes')} being checked
                            {page.hasMore ? ` · ${page.results.length} of ${page.count} reports loaded` : null}
                        </>
                    ) : null}
                </div>
                <MonitoringScopeControl />
            </div>
            {loadFailed ? (
                <div className="flex flex-col items-center gap-2 rounded border border-primary p-6 text-center text-sm">
                    <span>
                        Couldn't load the fixes being checked. Try again, and if it keeps happening, refresh the page.
                    </span>
                    <LemonButton size="small" type="secondary" onClick={() => loadReports()}>
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
                            <span>No fixes connected to you are being checked or finished in the last 14 days.</span>
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => setScope({ ...scope, everyone: true })}
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
                                onClick={() => loadMore()}
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
