// Kept in step with `flatten_markdown` (backend/observation_formatting.py), which documents the table.
const FENCE_RE = /^ {0,3}(?:```|~~~)/
const RULE_RE = /^ {0,3}(?:[-*_]\s*){3,}$/
const HEADING_RE = /^ {0,3}#{1,6}\s+/
const QUOTE_RE = /^ {0,3}>\s?/
const BULLET_RE = /^\s*(?:[-*+]|\d{1,9}[.)])\s+/
const IMAGE_RE = /!\[([^\]]*)\]\([^)]*\)/g
const LINK_RE = /\[([^\]]*)\]\([^)]*\)/g
const LINK_DEFINITION_RE = /^ {0,3}\[[^\]]+\]:\s*\S+(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*$/
const REFERENCE_RE = /!?\[([^\]]*)\]\[[^\]]*\]/g
const CODE_SPAN_RE = /`+([^`]*)`+/g
const STRONG_RE = /(\*\*|__)(\S(?:.*?\S)?)\1/g
const STRIKE_RE = /~~(\S(?:.*?\S)?)~~/g
// Captured rather than a lookbehind, which breaks chunk parsing.
const EMPHASIS_RE = /(^|[^\w*_])([*_])(\S(?:.*?\S)?)\2(?![\w*_])/g
const ESCAPE_RE = /\\([\\`*_{}[\]()#+\-.!>~|])/g
const SENTENCE_ENDINGS = '.!?:;,'

/** Markdown-bearing model text on one line, for surfaces with room for a fragment, not a rendered block. */
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
