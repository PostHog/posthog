import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { membersLogic } from '~/models/membersLogic'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { reportNotesFromArtefacts } from '../../utils/reportNotes'
import { ReportNoteComposer } from './ReportNoteComposer'
import { ReportNoteRow } from './ReportNoteRow'

/**
 * The notes people left on the report, at the end of its body. Activity records the same notes as
 * quotes in the report's history, so this list is where they are read and retired.
 */
export function ReportNotesSection({ report }: { report: SignalReport }): JSX.Element {
    const { reportArtefacts } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const notes = reportNotesFromArtefacts(reportArtefacts ?? [])
    const mentionsEnabled = useFeatureFlag('SIGNALS_REPORT_NOTE_MENTIONS')
    const { ensureAllMembersLoaded } = useActions(membersLogic)

    // Member chips in the notes and the mention picker both read the organization's members.
    useEffect(() => {
        if (mentionsEnabled) {
            ensureAllMembersLoaded()
        }
    }, [mentionsEnabled, ensureAllMembersLoaded])

    return (
        <div className="mb-4 flex flex-col gap-2" data-attr="inbox-report-notes">
            {notes.length > 0 && (
                <>
                    <span className="text-xs font-semibold text-secondary">Notes · {notes.length}</span>
                    <div className="flex flex-col rounded border border-primary bg-surface-primary">
                        {notes.map((note) => (
                            <ReportNoteRow key={note.id} reportId={report.id} note={note} />
                        ))}
                    </div>
                </>
            )}
            <ReportNoteComposer report={report} />
        </div>
    )
}
