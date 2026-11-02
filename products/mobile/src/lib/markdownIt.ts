import { MarkdownIt } from 'react-native-markdown-display'

/**
 * markdown-it 10's autolink rule copies the rest of the text and searches it for `>` at every `<`, which costs
 * O(n^2) on a reply with many `<`. This rule uses the same two patterns as sticky regexes, so each attempt
 * reads only the characters that it matches.
 */
// biome-ignore lint/suspicious/noControlCharactersInRegex: the class excludes control characters and spaces from a URL, as markdown-it does.
const AUTOLINK = /<([a-zA-Z][a-zA-Z0-9+.-]{1,31}):([^<>\x00-\x20]*)>/y
const AUTOLINK_EMAIL =
    /<([a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*)>/y

/**
 * The parser for text the server or an agent wrote. Each call returns a new instance, so a caller can add its own
 * plugins without changing the others.
 *
 * `html: false` renders raw HTML as text, so the text can never inject markup.
 * `linkify: false` keeps linkify-it off the parse path. Its scanner copies the rest of the text at each
 * scheme match, so a long `mailto:` repetition in a saved reply blocks the JS thread (GHSA-v245-v573-v5vm).
 * `[text](url)` links and `<https://...>` autolinks do not use linkify and still render as links.
 */
export function createMarkdownIt(): MarkdownIt {
    const markdownIt = MarkdownIt({ html: false, linkify: false, typographer: false })
    markdownIt.inline.ruler.at('autolink', (state, silent) => {
        if (state.src.charCodeAt(state.pos) !== 0x3c) return false
        for (const [pattern, scheme] of [
            [AUTOLINK, ''],
            [AUTOLINK_EMAIL, 'mailto:'],
        ] as const) {
            pattern.lastIndex = state.pos
            const match = pattern.exec(state.src)
            if (!match) continue
            const url = match[0].slice(1, -1)
            const href = state.md.normalizeLink(scheme + url)
            if (!state.md.validateLink(href)) return false
            if (!silent) {
                const open = state.push('link_open', 'a', 1)
                open.attrs = [['href', href]]
                open.markup = 'autolink'
                open.info = 'auto'
                state.push('text', '', 0).content = state.md.normalizeLinkText(url)
                const close = state.push('link_close', 'a', -1)
                close.markup = 'autolink'
                close.info = 'auto'
            }
            state.pos += match[0].length
            return true
        }
        return false
    })
    return markdownIt
}
