/** Characters that draw nothing but are neither `\p{C}` nor a space, so they would show as an empty gap. */
const BLANK_CHARACTERS = '\\u034F\\u115F\\u1160\\u17B4\\u17B5\\u2800\\u3164\\uFFA0'

// A joiner or selector inside an emoji is part of what the user sees. Alternatives are tried in order, so the first
// one keeps an emoji whole and the rest escape those characters anywhere else.
const KEPT_OR_ESCAPED = new RegExp(
    [
        '(?<emoji>\\p{Extended_Pictographic}[\\uFE0F\\p{Emoji_Modifier}]?(?:\\u200D\\p{Extended_Pictographic}[\\uFE0F\\p{Emoji_Modifier}]?)*)',
        // Control, format, unpaired and unassigned characters, line separators, and every space that isn't U+0020.
        `[\\p{C}\\p{Zl}\\p{Zp}\\p{Variation_Selector}${BLANK_CHARACTERS}]`,
        '(?! )\\p{Zs}',
        // Spaces that would push the rest of the text out of view.
        '(?<=  ) ',
        // Marks stacked until they cover the lines around them. No language stacks this many.
        '(?<=\\p{M}{4})\\p{M}',
        // What could close a quote or a code fence, or look like a tag.
        '["\\\\`]',
        '<(?=[/!?a-zA-Z])',
    ].join('|'),
    'gu'
)

function escapeUnits(character: string): string {
    if (character === '"' || character === '\\') {
        return `\\${character}`
    }
    if (character === '\n') {
        return '\\n'
    }
    return Array.from({ length: character.length }, (_, index) => character.charCodeAt(index))
        .map((unit) => `\\u${unit.toString(16).padStart(4, '0')}`)
        .join('')
}

/**
 * Quotes text that someone else wrote, as one line that can't end its own quotes.
 *
 * The cut marker stands outside the quotes, so the text can't fake it. Put the result inside a fenced code block, so
 * that the markdown in it shows as it is.
 */
export function quoteUntrusted(text: string, maxCharacters: number): string {
    const characters = Array.from(text)
    const quoted = characters
        .slice(0, maxCharacters)
        .join('')
        .replace(KEPT_OR_ESCAPED, (match, ...rest) => (rest.at(-1).emoji ? match : escapeUnits(match)))
    const cut = characters.length - maxCharacters
    return cut > 0 ? `"${quoted}" [cut: ${cut} more characters]` : `"${quoted}"`
}
