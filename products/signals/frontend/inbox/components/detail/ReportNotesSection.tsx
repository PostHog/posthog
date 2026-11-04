import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { reportNoteAudience, reportNotesLogic } from '../../logics/reportNotesLogic'
import { isDirectScoutNote } from '../../logics/scoutNotesLogic'
import { SignalReport } from '../../types'
import { stripReportNotePrefix } from '../../utils/reportNotes'
import { linkReportIdsInNote } from '../../utils/scoutMemoryPresentation'
import { ScoutNoteRow } from '../config/scouts/ScoutNoteRow'
import { DetailSection } from './DetailSection'

/**
 * What the scouts have been told about this report: notes people left from it, plus the ones the
 * inbox forwarded when it was dismissed, discussed, or rated. Hidden until there is a note, like the
 * Activity section, since most reports carry none.
 */
export function ReportNotesSection({
    report,
    onToggleCollapsed,
}: {
    report: SignalReport
    onToggleCollapsed?: (collapsed: boolean) => void
}): JSX.Element | null {
    const logic = reportNotesLogic({ reportId: report.id, reportScoutName: report.scout_name ?? null })
    const { activeNotes, notesLoadFailed, scoutNamesBySkill } = useValues(logic)
    const { deleteNote, loadNotes } = useActions(logic)

    if (!notesLoadFailed && activeNotes.length === 0) {
        return null
    }

    const thisReport = new Map([[report.id.toLowerCase(), { id: report.id, title: report.title }]])

    return (
        <DetailSection
            icon={<IconPencil />}
            title="Notes"
            collapsible
            onToggleCollapsed={onToggleCollapsed}
            meta={
                activeNotes.length > 0 ? (
                    <span className="text-xs text-tertiary tabular-nums">{activeNotes.length}</span>
                ) : undefined
            }
        >
            {activeNotes.length === 0 ? (
                <div className="flex items-center gap-2 text-xs text-danger">
                    <span>Couldn't load the notes on this report.</span>
                    <LemonButton size="xsmall" type="secondary" onClick={() => loadNotes()}>
                        Try again
                    </LemonButton>
                </div>
            ) : (
                <div className="flex flex-col rounded border border-primary bg-surface-primary">
                    {activeNotes.map((note) => (
                        <ScoutNoteRow
                            key={note.id}
                            note={note}
                            audience={reportNoteAudience(note.skill_name, scoutNamesBySkill)}
                            content={linkReportIdsInNote(stripReportNotePrefix(report.id, note.content), thisReport, {
                                truncateUnmatched: !isDirectScoutNote(note),
                            })}
                            onDelete={() => deleteNote(note.id)}
                        />
                    ))}
                </div>
            )}
        </DetailSection>
    )
}
