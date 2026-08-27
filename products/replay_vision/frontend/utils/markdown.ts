// Markdown a scanner can emit in its free-text fields. Block markers are matched per line, the way a
// markdown parser reads them; inline markers are matched anywhere on the line. Mirrors the backend's
// `flatten_markdown` (products/replay_vision/backend/observation_formatting.py), which does the same job
// for the surfaces that never reach a browser.
const FENCE_RE = /^ {0,3}(?:```|~~~)/
const RULE_RE = /^ {0,3}(?:[-*_]\s*){3,}$/
const HEADING_RE = /^ {0,3}#{1,6}\s+/
const QUOTE_RE = /^ {0,3}>\s?/
const BULLET_RE = /^\s*(?:[-*+]|\d{1,9}[.)])\s+/
const IMAGE_RE = /!\[([^\]]*)\]\([^)]*\)/g
const LINK_RE = /\[([^\]]*)\]\([^)]*\)/g
// A link reference definition is a whole line of pure syntax, so the line goes. Its `[text][ref]` and
// `[text][]` usages keep their label. Bare `[text]` is left alone: in prose it is far more often a real
// bracket ("clicked [Save]") than a shortcut reference.
// The definition has to be the entire line — a space-free destination and an optional title, nothing
// after. Matching just the prefix would eat a sentence that merely opens the same way, such as
// "[Save]: clicked twice before it took".
const LINK_DEFINITION_RE = /^ {0,3}\[[^\]]+\]:\s*\S+(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*$/
const REFERENCE_RE = /!?\[([^\]]*)\]\[[^\]]*\]/g
const CODE_SPAN_RE = /`+([^`]*)`+/g
const STRONG_RE = /(\*\*|__)(\S(?:.*?\S)?)\1/g
const STRIKE_RE = /~~(\S(?:.*?\S)?)~~/g
// The captured leading character and the lookahead keep `snake_case` and `2 * 3 * 4` intact: an
// underscore or star touching a word character on the outside is punctuation the model meant literally,
// not an emphasis delimiter. Captured rather than a lookbehind, which breaks chunk parsing.
const EMPHASIS_RE = /(^|[^\w*_])([*_])(\S(?:.*?\S)?)\2(?![\w*_])/g
const ESCAPE_RE = /\\([\\`*_{}[\]()#+\-.!>~|])/g
// Terminal punctuation, after which one flattened block runs into the next without a sentence break.
const SENTENCE_ENDINGS = '.!?:;,'

/**
 * Markdown-bearing model text folded onto a single line of readable plain prose.
 *
 * Reasoning renders as markdown wherever there is room for it, but the places that only have room for a
 * fragment — a seekbar hover snippet, the dock's collapsed preview — would show the raw `**` and `-`
 * instead. Blocks join with a sentence break so a flattened list still reads as prose.
 */
export function flattenMarkdownToLine(text: string): string {
    let out = ''
    for (const raw of text.split('\n')) {
        if (FENCE_RE.test(raw) || RULE_RE.test(raw) || LINK_DEFINITION_RE.test(raw)) {
            continue
        }
        const block = raw
            .replace(HEADING_RE, '')
            .replace(QUOTE_RE, '')
            .replace(BULLET_RE, '')
            .replace(IMAGE_RE, '$1')
            .replace(LINK_RE, '$1')
            .replace(REFERENCE_RE, '$1')
            .replace(CODE_SPAN_RE, '$1')
            .replace(STRONG_RE, '$2')
            .replace(STRIKE_RE, '$1')
            .replace(EMPHASIS_RE, '$1$3')
            .replace(ESCAPE_RE, '$1')
            .split(/\s+/)
            .filter(Boolean)
            .join(' ')
        if (!block) {
            continue
        }
        out += out ? `${SENTENCE_ENDINGS.includes(out.slice(-1)) ? ' ' : '. '}${block}` : block
    }
    return out
}
