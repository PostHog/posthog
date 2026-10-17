import type { ReactElement } from 'react'
import { StyleSheet, Text } from 'react-native'
import Markdown, { MarkdownIt, type RenderRules } from 'react-native-markdown-display'
import { isMermaidLang } from '@/lib/mermaid'
import { colors, fonts, radii, type } from '@/ui/tokens'
import { InsightCard } from './InsightCard'
import { MermaidDiagram } from './MermaidDiagram'
import { ObjectChip } from './ObjectChip'
import { type ObjectCardSpec, type ObjectRef, objectTagsPlugin } from './objectTags'
import { QueryCard } from './QueryCard'
import { openReplyUrl, resolveReplyLink } from './webLinks'

/**
 * `html: false` renders raw HTML in a reply as text, so a reply can never inject markup.
 * `linkify: false` keeps linkify-it off the parse path. Its scanner copies the rest of the text at each
 * scheme match, so a long `mailto:` repetition in a saved reply blocks the JS thread (GHSA-v245-v573-v5vm).
 * `[text](url)` links and `<https://...>` autolinks do not use linkify and still render as links.
 */
const markdownIt = MarkdownIt({ html: false, linkify: false, typographer: false }).use(objectTagsPlugin)

markdownIt.core.ruler.after('block', 'closed_fences', (state) => {
    const lines = state.src.split('\n')
    for (const token of state.tokens) {
        if (token.type === 'fence' && token.map) {
            const last = lines[token.map[1] - 1]?.replace(/^(?:\s*>\s*)+/, '').trim() || ''
            token.meta = { closed: new RegExp(`^${token.markup[0]}{${token.markup.length},}\\s*$`).test(last) }
        }
    }
})

/**
 * markdown-it 10's autolink rule copies the rest of the text and searches it for `>` at every `<`, which costs
 * O(n^2) on a reply with many `<`. This rule uses the same two patterns as sticky regexes, so each attempt
 * reads only the characters that it matches.
 */
// biome-ignore lint/suspicious/noControlCharactersInRegex: the class excludes control characters and spaces from a URL, as markdown-it does.
const AUTOLINK = /<([a-zA-Z][a-zA-Z0-9+.-]{1,31}):([^<>\x00-\x20]*)>/y
const AUTOLINK_EMAIL =
    /<([a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*)>/y

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

const rules: RenderRules = {
    // Remote images in a reply would load from any host; the thread drops them.
    image: () => null,
    object_ref: (node) => (
        <ObjectChip key={node.key} target={(node as unknown as { sourceMeta: ObjectRef }).sourceMeta} />
    ),
    object_card: (node) => {
        const spec = (node as unknown as { sourceMeta: ObjectCardSpec }).sourceMeta
        return spec.mode === 'insight' ? (
            <InsightCard key={node.key} shortId={spec.shortId} title={spec.title} />
        ) : (
            <QueryCard key={node.key} query={spec.query} title={spec.title} />
        )
    },
    fence: (node, _children, _parents, styles) => {
        const fallback = (
            <Text key={node.key} style={styles.fence}>
                {node.content}
            </Text>
        )
        const meta = node as unknown as { sourceMeta?: { closed?: boolean }; sourceInfo?: string }
        return isMermaidLang(meta.sourceInfo) && meta.sourceMeta?.closed ? (
            <MermaidDiagram key={node.key} code={node.content} fallback={fallback} />
        ) : (
            fallback
        )
    },
}

function openLink(url: string): boolean {
    const resolved = resolveReplyLink(url)
    if (resolved) {
        openReplyUrl(resolved, 'markdown', { appLink: resolved !== url })
    }
    // false stops the library from opening the unresolved URL itself.
    return false
}

/** A snapshot can end right after a list marker, which would render as an empty bullet until the next one. */
const TRAILING_LIST_MARKER = /\n[ \t]*(?:[-*+]|\d+[.)])[ \t]*$/

interface ChatMarkdownProps {
    text: string
    streaming?: boolean
    tone?: 'reply' | 'thought'
}

export function ChatMarkdown({ text, streaming = false, tone = 'reply' }: ChatMarkdownProps): ReactElement {
    return (
        <Markdown
            markdownit={markdownIt}
            rules={rules}
            style={tone === 'thought' ? thoughtStyles : replyStyles}
            onLinkPress={openLink}
        >
            {streaming ? text.replace(TRAILING_LIST_MARKER, '') : text}
        </Markdown>
    )
}

const code = {
    fontFamily: fonts.mono,
    color: colors.ink,
} as const

const replyStyles = StyleSheet.create({
    body: {
        fontSize: 16,
        lineHeight: 23.2,
        color: colors.ink,
    },
    paragraph: {
        marginTop: 0,
        marginBottom: 10,
    },
    heading1: { ...type.sheetTitleLarge, marginTop: 4, marginBottom: 8 },
    heading2: { ...type.sheetTitle, marginTop: 4, marginBottom: 8 },
    heading3: { ...type.sectionHeader, marginTop: 4, marginBottom: 6 },
    heading4: { ...type.bodyStrong, marginTop: 4, marginBottom: 6 },
    heading5: { ...type.bodyStrong, marginTop: 4, marginBottom: 6 },
    heading6: { ...type.bodyStrong, marginTop: 4, marginBottom: 6 },
    strong: {
        fontWeight: '600',
    },
    link: {
        color: colors.ink,
        textDecorationLine: 'underline',
    },
    bullet_list: {
        marginBottom: 10,
    },
    ordered_list: {
        marginBottom: 10,
    },
    list_item: {
        marginBottom: 4,
    },
    bullet_list_icon: {
        color: colors.tertiary,
        marginLeft: 2,
        marginRight: 8,
    },
    ordered_list_icon: {
        color: colors.secondary,
        marginLeft: 2,
        marginRight: 8,
    },
    code_inline: {
        ...code,
        fontSize: 14,
        backgroundColor: colors.sunken,
        borderWidth: 0,
        borderRadius: 4,
        // The library default pads 10 on every side, which makes the line box taller than the text.
        padding: 0,
        paddingHorizontal: 4,
    },
    code_block: {
        ...code,
        ...type.mono,
        backgroundColor: colors.background,
        borderColor: colors.hairline,
        borderWidth: 1,
        borderRadius: radii.card,
        padding: 12,
        marginBottom: 10,
    },
    fence: {
        ...code,
        ...type.mono,
        backgroundColor: colors.background,
        borderColor: colors.hairline,
        borderWidth: 1,
        borderRadius: radii.card,
        padding: 12,
        marginBottom: 10,
    },
    blockquote: {
        backgroundColor: 'transparent',
        borderColor: colors.hairline,
        borderLeftWidth: 3,
        marginLeft: 0,
        paddingHorizontal: 12,
        paddingVertical: 0,
        marginBottom: 10,
    },
    hr: {
        backgroundColor: colors.hairline,
        height: 1,
        marginVertical: 12,
    },
    table: {
        borderColor: colors.hairline,
        borderWidth: 1,
        borderRadius: 8,
        marginBottom: 10,
    },
    tr: {
        borderBottomWidth: 1,
        borderColor: colors.hairline,
    },
    th: {
        padding: 8,
        fontWeight: '600',
    },
    td: {
        padding: 8,
    },
})

const thoughtCode = {
    fontFamily: fonts.mono,
    color: colors.muted,
    // Code inherits the italic body style, and italic monospace is hard to read.
    fontStyle: 'normal',
} as const

const thoughtHeading = { ...type.bodySmallStrong, color: colors.muted, marginTop: 4, marginBottom: 6 } as const

const thoughtStyles = StyleSheet.create({
    ...replyStyles,
    body: {
        ...type.bodySmall,
        color: colors.muted,
        fontStyle: 'italic',
    },
    heading1: thoughtHeading,
    heading2: thoughtHeading,
    heading3: thoughtHeading,
    heading4: thoughtHeading,
    heading5: thoughtHeading,
    heading6: thoughtHeading,
    link: {
        color: colors.muted,
        textDecorationLine: 'underline',
    },
    code_inline: {
        ...replyStyles.code_inline,
        ...thoughtCode,
        fontSize: 13,
    },
    code_block: {
        ...replyStyles.code_block,
        ...thoughtCode,
    },
    fence: {
        ...replyStyles.fence,
        ...thoughtCode,
    },
})
