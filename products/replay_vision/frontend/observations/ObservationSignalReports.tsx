import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { SignalReportStatusBadge } from 'products/signals/frontend/inbox/components/badges/SignalReportStatusBadge'
import { SignalReportStatus } from 'products/signals/frontend/inbox/types'
import { displayConventionalCommitTitle } from 'products/signals/frontend/inbox/utils/reportPresentation'

import { LabeledRow } from '../components/LabeledRow'
import { observationSignalReportsLogic } from './observationSignalReportsLogic'

// Mounted only when the observation emitted something, so a no-signal observation never queries.
function ReportsRow({ observationId }: { observationId: string }): JSX.Element {
    const { signalReports, signalReportsLoading, signalReportsUnavailable } = useValues(
        observationSignalReportsLogic({ observationId })
    )

    if (signalReportsLoading) {
        return (
            <LabeledRow label="Report">
                <LemonSkeleton className="h-4 w-40" />
            </LabeledRow>
        )
    }
    if (signalReportsUnavailable) {
        return (
            <LabeledRow label="Report">
                <span className="text-muted">Could not load</span>
            </LabeledRow>
        )
    }
    if (!signalReports?.length) {
        // The lookup window is bounded, so an old observation can have a report this does not find.
        return (
            <LabeledRow label="Report">
                <span className="text-muted">None found</span>
            </LabeledRow>
        )
    }
    return (
        <LabeledRow label={signalReports.length === 1 ? 'Report' : 'Reports'}>
            <ul className="flex flex-col list-none pl-0 m-0 rounded border border-primary divide-y divide-primary overflow-hidden">
                {signalReports.map((report) => (
                    <li key={report.id}>
                        {/* The whole row is the link, so the target matches what reads as one item. */}
                        <Link
                            to={urls.inboxReport('reports', report.id)}
                            data-attr="vision-observation-open-signal-report"
                            className="flex flex-col gap-1 px-2 py-1.5 hover:bg-surface-secondary"
                        >
                            <span className="leading-snug">
                                {capitalizeFirstLetter(displayConventionalCommitTitle(report.title, 'Untitled report'))}
                            </span>
                            <span>
                                <SignalReportStatusBadge status={report.status as SignalReportStatus} />
                            </span>
                        </Link>
                    </li>
                ))}
            </ul>
        </LabeledRow>
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
        <>
            <LabeledRow label="Signals emitted">
                <span>{signalsCount}</span>
            </LabeledRow>
            {signalsCount > 0 && <ReportsRow observationId={observationId} />}
        </>
    )
}
