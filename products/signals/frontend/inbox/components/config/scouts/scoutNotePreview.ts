/** Notes run to hundreds of words, and the panel sits in a narrow sidebar next to the reports. */
export const NOTE_PREVIEW_CHARS = 280

/** Counted in graphemes, so a flag, an accent or a family emoji is one character and stays whole. */
const GRAPHEMES = new Intl.Segmenter('und', { granularity: 'grapheme' })

/**
 * What GFM autolinks on sight: a scheme, a bare `www.` host, an email address. A cut inside one
 * still links, sending a reader somewhere the note never pointed, so the preview drops it whole.
 */
const SEVERED_LINK = /(?:[a-z][a-z0-9+.-]*:\/\/|\bwww\.|[\w.+-]+@)\S*$/i

/**
 * The opening of a note, short enough to sit in the sidebar. Cutting mid-word reads like a typo, so
 * back up to the last whitespace. Prose with no whitespace at all — CJK, say — cuts at the limit
 * instead, on a character boundary.
 */
export function scoutNotePreview(content: string): string {
    const characters = Array.from(GRAPHEMES.segment(content), ({ segment }) => segment)
    if (characters.length <= NOTE_PREVIEW_CHARS) {
        return content
    }
    const head = characters.slice(0, NOTE_PREVIEW_CHARS).join('')
    const wholeWords = head.replace(/\S*$/, '')
    return `${(wholeWords.trim() ? wholeWords : head.replace(SEVERED_LINK, '')).trimEnd()}…`
}
