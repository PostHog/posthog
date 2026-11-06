/** Notes run to hundreds of words, and the panel sits in a narrow sidebar next to the reports. */
export const NOTE_PREVIEW_CHARS = 280

/**
 * How far the cut travels back to land on a word boundary, counted in characters. Longer than a
 * word, short enough that a note opening with a label and continuing in a script without spaces
 * still gets a preview.
 */
const MAX_WORD_BACKTRACK = 40

/**
 * What GFM autolinks on sight: an `http(s)` URL, a bare `www.` host, an email address on a dotted
 * domain. A cut inside one still links, sending a reader somewhere the note never pointed, so the
 * preview drops it whole. Other schemes (`s3://`, `file://`) and a plain `a@b` without a dotted
 * domain are not autolinked, so they stay.
 */
const SEVERED_LINK = /(?:https?:\/\/|\bwww\.)\S*$|[\w.+-]+@[\w-]+(?:\.[\w-]+)+$/i

/**
 * A reference definition the cut ran through. A `[docs][d]` earlier in the note still resolves
 * against it, so the label renders as a live link to a shortened destination. The destination may
 * sit on the line below the label, which CommonMark allows. Only a cut that keeps the grapheme head
 * can sever a definition: backing up to whitespace stops before the destination, which leaves
 * `[d]:` and no definition at all.
 */
const SEVERED_DEFINITION = /(?:^|\n)[ \t]{0,3}\[[^\]\n]+\]:[ \t]*(?:\n[ \t]*)?[^\n]*$/

let segmenter: Intl.Segmenter | null | undefined

/**
 * The grapheme segmenter, built on first use and only if the browser has it. At module scope a
 * browser without `Intl.Segmenter` would fail the import and take the panel down, rather than just
 * showing long notes in full.
 */
function graphemeSegmenter(): Intl.Segmenter | null {
    if (segmenter === undefined) {
        segmenter = typeof Intl.Segmenter === 'function' ? new Intl.Segmenter('und', { granularity: 'grapheme' }) : null
    }
    return segmenter
}

/**
 * The first `limit` characters of a note as a person counts them — a flag, an accent or a family
 * emoji is one. Returns `null` when the note already fits, or when the browser has no segmenter to
 * count graphemes with: rather than split a character, such a browser shows the note in full.
 */
function head(content: string, limit: number): string[] | null {
    // A character is one code unit or more, so this rules out most notes without segmenting them.
    if (content.length <= limit) {
        return null
    }
    const segments = graphemeSegmenter()
    if (!segments) {
        return null
    }
    const characters: string[] = []
    for (const { segment } of segments.segment(content)) {
        characters.push(segment)
        // One character past the limit is enough to know the note is longer than the preview, and
        // stops the walk short of a body that can run to thousands of characters.
        if (characters.length > limit) {
            return characters.slice(0, limit)
        }
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
    let boundary = -1
    for (let i = opening.length - 1; i >= 0; i--) {
        if (opening[i].trim() === '') {
            boundary = i
            break
        }
    }
    const kept = boundary > 0 ? opening.slice(0, boundary).join('').trimEnd() : ''
    const backtrack = opening.length - 1 - boundary
    if (kept && backtrack <= MAX_WORD_BACKTRACK) {
        return `${kept}…`
    }
    return `${opening.join('').replace(SEVERED_LINK, '').replace(SEVERED_DEFINITION, '').trimEnd()}…`
}
