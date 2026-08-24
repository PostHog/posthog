/** Notes run to hundreds of words, and the panel sits in a narrow sidebar next to the reports. */
export const NOTE_PREVIEW_CHARS = 280

/**
 * How far the cut travels back to land on a word boundary. Longer than a word, short enough that a
 * note opening with a label and continuing in a script without spaces still gets a preview.
 */
const MAX_WORD_BACKTRACK = 40

/**
 * What GFM autolinks on sight: a scheme, a bare `www.` host, an email address on a dotted domain. A
 * cut inside one still links, sending a reader somewhere the note never pointed, so the preview
 * drops it whole. An `a@b` with no dot after it is not a link, and stays.
 */
const SEVERED_LINK = /(?:[a-z][a-z0-9+.-]*:\/\/|\bwww\.)\S*$|[\w.+-]+@[\w-]+(?:\.[\w-]+)+$/i

let segmenter: Intl.Segmenter | null | undefined

/**
 * Characters as a person counts them, so a flag, an accent or a family emoji is one and stays
 * whole. Built on first use, and only if the browser has it: at module scope a browser without
 * `Intl.Segmenter` fails the import and takes the panel with it, rather than losing only the
 * grapheme precision. The fallback iterates code points, which still never splits a character.
 */
function* characters(content: string): Generator<string> {
    if (segmenter === undefined) {
        segmenter = typeof Intl.Segmenter === 'function' ? new Intl.Segmenter('und', { granularity: 'grapheme' }) : null
    }
    if (!segmenter) {
        yield* content
        return
    }
    for (const { segment } of segmenter.segment(content)) {
        yield segment
    }
}

/** The first `limit` characters, or `null` for a note already that short. */
function head(content: string, limit: number): string | null {
    // A character is one code unit or more, so most notes never get segmented, and the loop below
    // stops one character past the limit rather than walking a body thousands of characters long.
    if (content.length <= limit) {
        return null
    }
    let taken = ''
    let count = 0
    for (const character of characters(content)) {
        if (count === limit) {
            return taken
        }
        taken += character
        count += 1
    }
    return null
}

/**
 * The opening of a note, short enough to sit in the sidebar. Cutting mid-word reads like a typo, so
 * back up to the last whitespace. Prose with no whitespace within reach — CJK, say — cuts at the
 * limit instead, on a character boundary.
 */
export function scoutNotePreview(content: string): string {
    const opening = head(content, NOTE_PREVIEW_CHARS)
    if (opening === null) {
        return content
    }
    const wholeWords = opening.replace(/\S*$/, '').trimEnd()
    const nearby = wholeWords && opening.length - wholeWords.length <= MAX_WORD_BACKTRACK
    return `${nearby ? wholeWords : opening.replace(SEVERED_LINK, '').trimEnd()}…`
}
