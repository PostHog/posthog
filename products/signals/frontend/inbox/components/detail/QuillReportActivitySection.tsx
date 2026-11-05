import { useValues } from 'kea'

import { IconClockRewind } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { selectVisibleReportActivity } from './artefactTypes'
import { QuillArtefactLogList } from './QuillArtefactLogList'
import { QuillDetailSection } from './QuillDetailSection'

/** The quill sibling of `ReportActivitySection`. Hidden entirely until at least one artefact is worth showing. */
export function QuillReportActivitySection({ report }: { report: SignalReport }): JSX.Element | null {
    const { reportArtefacts, reportSignals, reportTasks } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )

    // The count matches what the log renders: the log hides internal retry records.
    const artefacts = selectVisibleReportActivity(reportArtefacts ?? [])
    if (artefacts.length === 0) {
        return null
    }

    // Hand the tasks the Runs section already loaded to the `task_run` rows, so they don't re-fetch them.
    const knownTasks = new Map((reportTasks ?? []).map((entry) => [entry.task.id, entry.task]))
    const knownSignals = new Map((reportSignals ?? []).map((signal) => [signal.signal_id, signal]))

    return (
        <QuillDetailSection
            icon={<IconClockRewind />}
            title="Activity"
            collapsible
            defaultCollapsed
            meta={
                <Text size="xs" render={<span />} className="text-subtle-foreground tabular-nums">
                    {artefacts.length} {artefacts.length === 1 ? 'entry' : 'entries'}
                </Text>
            }
        >
            <QuillArtefactLogList
                reportId={report.id}
                artefacts={artefacts}
                knownTasks={knownTasks}
                knownSignals={knownSignals}
                pullRequests={report.pull_requests}
                collapsedNoteCount={report.collapsed_note_count ?? 0}
            />
        </QuillDetailSection>
    )
}
