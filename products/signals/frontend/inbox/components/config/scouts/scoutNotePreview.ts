/** Notes run to hundreds of words, and the panel sits in a narrow sidebar next to the reports. */
export const NOTE_PREVIEW_CHARS = 280

/** A cut inside a URL still autolinks, sending a reader somewhere the note never pointed. */
const TRAILING_URL = /(?:https?:\/\/|www\.)\S*$/i

/**
 * The opening of a note, short enough to sit in the sidebar. Cutting mid-word reads like a typo, so
 * back up to the last whitespace. Prose with no whitespace at all — CJK, say — cuts at the limit
 * instead, counted in code points so the cut never lands inside a character.
 */
export function scoutNotePreview(content: string): string {
    const characters = Array.from(content)
    if (characters.length <= NOTE_PREVIEW_CHARS) {
        return content
    }
    const head = characters.slice(0, NOTE_PREVIEW_CHARS).join('')
    const wholeWords = head.replace(/\S*$/, '')
    return `${(wholeWords.trim() ? wholeWords : head.replace(TRAILING_URL, '')).trimEnd()}…`
}
