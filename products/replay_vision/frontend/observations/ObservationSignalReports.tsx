import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { urls } from 'scenes/urls'

import { LabeledRow } from '../components/LabeledRow'
import { observationSignalReportsLogic } from './observationSignalReportsLogic'

/** The signals this observation emitted, and the inbox reports they were grouped into. */
export function ObservationSignalReports({
    observationId,
    signalsCount,
}: {
    observationId: string
    signalsCount: number
}): JSX.Element {
    const { signalReports, signalReportsLoading } = useValues(observationSignalReportsLogic({ observationId }))

    return (
        <LabeledRow label="Signals">
            <div className="flex flex-col items-start gap-1">
                <span>Emitted ({signalsCount})</span>
                {signalsCount > 0 &&
                    (signalReportsLoading ? (
                        <LemonSkeleton className="h-4 w-40" />
                    ) : signalReports?.length ? (
                        signalReports.map((report) => (
                            <Link
                                key={report.id}
                                to={urls.inboxReport('reports', report.id)}
                                data-attr="vision-observation-open-signal-report"
                            >
                                {report.title || 'Untitled report'}
                            </Link>
                        ))
                    ) : (
                        <span className="text-muted">Not grouped into a report yet</span>
                    ))}
            </div>
        </LabeledRow>
    )
}
