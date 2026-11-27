// These draw nothing, but Unicode classes them as letters, marks or symbols.
const BLANK = '\\u034F\\u115F\\u1160\\u17B4\\u17B5\\u2800\\u3164\\uFFA0'
const EMOJI =
    '\\p{Extended_Pictographic}[\\uFE0F\\p{Emoji_Modifier}]?(?:\\u200D\\p{Extended_Pictographic}[\\uFE0F\\p{Emoji_Modifier}]?)*'
const HIDDEN = `[\\p{C}\\p{Zl}\\p{Zp}\\p{Variation_Selector}${BLANK}]|(?! )\\p{Zs}`
const LONG_GAP = '(?<=  ) '
const STACKED_MARK = '(?<=\\p{M}{4})\\p{M}'
const QUOTE_FENCE_OR_TAG = '["\\\\`]|<(?=[/!?a-zA-Z])'

// Emoji come first, so the joiners and selectors inside one stay.
const KEPT_OR_ESCAPED = new RegExp(
    `(?<emoji>${EMOJI})|${HIDDEN}|${LONG_GAP}|${STACKED_MARK}|${QUOTE_FENCE_OR_TAG}`,
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

// One line that can't end its own quotes. Put it inside a fenced code block, so markdown in it shows as it is.
export function quoteUntrusted(text: string, maxCharacters: number): string {
    const characters = Array.from(text)
    const quoted = characters
        .slice(0, maxCharacters)
        .join('')
        .replace(KEPT_OR_ESCAPED, (match, ...rest) => (rest.at(-1).emoji ? match : escapeUnits(match)))
    const cut = characters.length - maxCharacters
    return cut > 0 ? `"${quoted}" [cut: ${cut} more characters]` : `"${quoted}"`
}
