import { useValues } from 'kea'

import { IconClockRewind } from '@posthog/icons'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { ArtefactLogList } from './ArtefactLogList'
import { selectVisibleReportActivity } from './artefactTypes'
import { DetailSection } from './DetailSection'

/**
 * The report's chronological work-log: every artefact (judgments, findings, code references, diffs,
 * commits, task runs, notes, reviewers) rendered as a timeline entry. Reads the artefacts the detail
 * logic already loads (and polls while the report is active), so it stays in sync with the rest of
 * the detail view. Hidden entirely until at least one artefact is worth showing. Mirrors desktop
 * `ReportActivitySection`.
 */
export function ReportActivitySection({ report }: { report: SignalReport }): JSX.Element | null {
    const { reportArtefacts, reportSignals, reportTasks } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )

    // The badge counts what the log renders: `ArtefactLogList` hides internal retry records, so a
    // raw artefact count would promise entries the timeline never shows.
    const artefacts = selectVisibleReportActivity(reportArtefacts ?? [])
    if (artefacts.length === 0) {
        return null
    }

    // The logic already resolved the research/implementation tasks; hand them to the `task_run` rows
    // so they don't re-fetch the same tasks the Runs section just loaded.
    const knownTasks = new Map((reportTasks ?? []).map((entry) => [entry.task.id, entry.task]))
    const knownSignals = new Map((reportSignals ?? []).map((signal) => [signal.signal_id, signal]))

    return (
        <DetailSection
            icon={<IconClockRewind />}
            title="Activity"
            collapsible
            defaultCollapsed
            meta={
                <span className="text-xs text-tertiary tabular-nums">
                    {artefacts.length} {artefacts.length === 1 ? 'entry' : 'entries'}
                </span>
            }
        >
            <ArtefactLogList
                reportId={report.id}
                artefacts={artefacts}
                knownTasks={knownTasks}
                knownSignals={knownSignals}
                pullRequests={report.pull_requests}
            />
        </DetailSection>
    )
}
