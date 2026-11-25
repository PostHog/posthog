import type { ReportMonitoringSummaryApi } from 'products/signals/frontend/generated/api.schemas'

import { monitoringDisplayState, monitoringSummaryTimeline } from '../../utils/reportMonitoringSummary'
import { ReportCheckMonitoringTimeline } from '../detail/ReportCheckMonitoringTimeline'
import { MonitoringTime } from './MonitoringTime'

function waitingText(summary: ReportMonitoringSummaryApi, now: number): React.ReactNode {
    const nextReading = summary.lead_check?.next_measurement_at
    switch (monitoringDisplayState(summary, now)) {
        case 'window_ended':
            return 'The window has ended. The final checks are running now.'
        case 'readings_hidden':
            return "You don't have access to the data this check measures, so its readings are hidden."
        case 'final_check_only':
            return (
                <span>
                    The checks run when the window ends, <MonitoringTime iso={summary.ends_at} />. Nothing is measured
                    before then.
                </span>
            )
        default:
            return nextReading ? (
                <span>
                    The next reading is due <MonitoringTime iso={nextReading} />.
                </span>
            ) : null
    }
}

/** Stands in for the chart when there is nothing to draw yet, or the viewer may not see it. */
export function MonitoringWaitingNote({
    summary,
    now,
}: {
    summary: ReportMonitoringSummaryApi
    now: number
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1 rounded bg-surface-secondary p-3 text-sm text-secondary">
            {waitingText(summary, now)}
            <ReportCheckMonitoringTimeline timeline={monitoringSummaryTimeline(summary, now)} />
        </div>
    )
}
