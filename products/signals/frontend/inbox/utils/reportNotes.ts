import { SCOUT_NOTE_MAX_CHARS } from '../logics/scoutNotesLogic'

/**
 * A note left from a report names the report by id and nothing else. The id lets a scout fetch the
 * report and lets the report find its notes again through the list's `text` filter. The title stays
 * out because a directly left note is listed to callers who may not read reports.
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
