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
 * A note a person left on the report. Agents write both kinds too, through the MCP notes tool and the
 * artefact API, and those stay in Activity only, so the Notes list reads as what people said about the
 * report. An agent note also carries the human principal in `created_by`, so without this check the row
 * would put automated text under that person's name and avatar.
 */
export function isPersonReportNote(artefact: SignalReportArtefact): boolean {
    return (artefact.type === 'scout_note_left' || artefact.type === 'note') && artefact.actor_kind === 'user'
}

/** Oldest first, so a new note lands at the bottom next to the box it was written in. */
export function reportNotesFromArtefacts(artefacts: SignalReportArtefact[]): SignalReportArtefact[] {
    return artefacts.filter(isPersonReportNote).sort((a, b) => a.created_at.localeCompare(b.created_at))
}

export type NoteSegment = { kind: 'text'; text: string } | { kind: 'member'; id: number } | { kind: 'role'; id: string }

// A token counts only at the start of the text or after whitespace, the same rule as the backend and LemonMarkdown.
const NOTE_MENTION_TOKEN =
    /(?<!\S)@(?:member:(\d+)|role:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}))/gi

/** Splits note text into plain runs and the people and roles it mentions, in order. */
export function splitNoteMentions(text: string): NoteSegment[] {
    const segments: NoteSegment[] = []
    let last = 0
    for (const match of text.matchAll(NOTE_MENTION_TOKEN)) {
        if (match.index > last) {
            segments.push({ kind: 'text', text: text.slice(last, match.index) })
        }
        segments.push(
            match[1] ? { kind: 'member', id: Number(match[1]) } : { kind: 'role', id: match[2].toLowerCase() }
        )
        last = match.index + match[0].length
    }
    if (last < text.length) {
        segments.push({ kind: 'text', text: text.slice(last) })
    }
    return segments
}

/** How many people and roles a note mentions, for analytics. Counts tokens, never names. */
export function noteMentionCounts(text: string): { mention_count: number; role_mention_count: number } {
    const segments = splitNoteMentions(text)
    const unique = (kind: 'member' | 'role'): number =>
        new Set(segments.flatMap((segment) => (segment.kind === kind ? [segment.id] : []))).size
    return { mention_count: unique('member'), role_mention_count: unique('role') }
}
