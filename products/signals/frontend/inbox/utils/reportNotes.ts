import { SCOUT_NOTE_MAX_CHARS } from '../logics/scoutNotesLogic'

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
