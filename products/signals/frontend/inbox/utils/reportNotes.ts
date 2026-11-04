import { SCOUT_NOTE_MAX_CHARS } from '../logics/scoutNotesLogic'

/**
 * The notes API writes this prefix when a note is created with a `report_id` (`report_note_content`
 * in `report_scout_notes.py`). A report finds its notes by that id, and strips the prefix where it
 * would only repeat the report the reader is on.
 */
function reportNotePrefix(reportId: string): string {
    return `Note on inbox report \`${reportId}\`:\n\n`
}

/** What a person can type, so the prefixed note still fits under the create serializer's cap. */
export function reportNoteMaxChars(reportId: string): number {
    return SCOUT_NOTE_MAX_CHARS - reportNotePrefix(reportId).length
}

export function buildReportNoteContent(reportId: string, text: string): string {
    return `${reportNotePrefix(reportId)}${text}`
}

/** The note as its author typed it, for the report it was left on, where the prefix says nothing new. */
export function stripReportNotePrefix(reportId: string, content: string): string {
    const prefix = reportNotePrefix(reportId)
    return content.startsWith(prefix) ? content.slice(prefix.length) : content
}
