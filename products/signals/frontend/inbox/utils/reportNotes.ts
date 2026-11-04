import { SCOUT_NOTE_MAX_CHARS } from '../logics/scoutNotesLogic'
import type { SignalReportArtefact } from '../types'

/**
 * The notes API writes this prefix when a note is created with a `report_id` (`report_note_content`
 * in `report_scout_notes.py`), so the text a person types has to leave room for it.
 */
function reportNotePrefix(reportId: string): string {
    return `Note on inbox report \`${reportId}\`:\n\n`
}

/** What a person can type, so the prefixed note still fits under the create serializer's cap. */
export function reportNoteMaxChars(reportId: string): number {
    return SCOUT_NOTE_MAX_CHARS - reportNotePrefix(reportId).length
}

/**
 * A note a person left on the report. Agents also write `note` entries about their work, and those stay
 * in Activity only, so the Notes list reads as what people said about the report.
 */
export function isPersonReportNote(artefact: SignalReportArtefact): boolean {
    return artefact.type === 'scout_note_left' || (artefact.type === 'note' && artefact.actor_kind === 'user')
}

/** Oldest first, so a new note lands at the bottom next to the box it was written in. */
export function reportNotesFromArtefacts(artefacts: SignalReportArtefact[]): SignalReportArtefact[] {
    return artefacts.filter(isPersonReportNote).sort((a, b) => a.created_at.localeCompare(b.created_at))
}
