import { SignalReport, SignalReportArtefact } from '../../types'
import { ReportNoteComposer } from './ReportNoteComposer'
import { ReportNoteRow } from './ReportNoteRow'

export function QuillReportNotesSection({
    report,
    notes,
}: {
    report: SignalReport
    notes: SignalReportArtefact[]
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3" data-quill data-attr="inbox-report-notes">
            {notes.map((note) => (
                <ReportNoteRow key={note.id} reportId={report.id} note={note} />
            ))}
            <ReportNoteComposer report={report} />
        </div>
    )
}
