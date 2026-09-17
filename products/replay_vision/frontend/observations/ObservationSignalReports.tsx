import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { urls } from 'scenes/urls'

import { displayConventionalCommitTitle } from 'products/signals/frontend/inbox/utils/reportPresentation'

import { LabeledRow } from '../components/LabeledRow'
import { observationSignalReportsLogic } from './observationSignalReportsLogic'

// Mounted only when the observation emitted something, so a no-signal observation never queries.
function ReportLinks({ observationId }: { observationId: string }): JSX.Element {
    const { signalReports, signalReportsLoading, signalReportsUnavailable } = useValues(
        observationSignalReportsLogic({ observationId })
    )

    if (signalReportsLoading) {
        return <LemonSkeleton className="h-4 w-40" />
    }
    if (signalReportsUnavailable) {
        return <span className="text-muted">Could not load linked reports</span>
    }
    if (!signalReports?.length) {
        // The lookup window is bounded, so an old observation can have a report this does not find.
        return <span className="text-muted">No linked report found</span>
    }
    return (
        <>
            {signalReports.map((report) => (
                <Link
                    key={report.id}
                    to={urls.inboxReport('reports', report.id)}
                    data-attr="vision-observation-open-signal-report"
                >
                    {displayConventionalCommitTitle(report.title, 'Untitled report')}
                </Link>
            ))}
        </>
    )
}

/** The signals this observation emitted, and the inbox reports they were grouped into. */
export function ObservationSignalReports({
    observationId,
    signalsCount,
}: {
    observationId: string
    signalsCount: number
}): JSX.Element {
    return (
        <LabeledRow label="Signals">
            <div className="flex flex-col items-start gap-1">
                <span>Emitted ({signalsCount})</span>
                {signalsCount > 0 && <ReportLinks observationId={observationId} />}
            </div>
        </LabeledRow>
    )
}
