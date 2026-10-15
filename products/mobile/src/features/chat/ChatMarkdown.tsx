import type { ReactElement } from 'react'
import { Linking, StyleSheet, Text } from 'react-native'
import Markdown, { MarkdownIt, type RenderRules } from 'react-native-markdown-display'
import { isMermaidLang } from '@/lib/mermaid'
import { colors, fonts, radii, type } from '@/ui/tokens'
import { InsightCard } from './InsightCard'
import { MermaidDiagram } from './MermaidDiagram'
import { ObjectChip } from './ObjectChip'
import { type ObjectCardSpec, type ObjectRef, objectTagsPlugin } from './objectTags'
import { QueryCard } from './QueryCard'
import { resolveReplyLink } from './webLinks'

/** `html: false` renders raw HTML in a reply as text, so a reply can never inject markup. */
const markdownIt = MarkdownIt({ html: false, linkify: true, typographer: false }).use(objectTagsPlugin)

markdownIt.core.ruler.after('block', 'closed_fences', (state) => {
    const lines = state.src.split('\n')
    for (const token of state.tokens) {
        if (token.type === 'fence' && token.map) {
            const last = lines[token.map[1] - 1]?.replace(/^(?:\s*>\s*)+/, '').trim() || ''
            token.meta = { closed: new RegExp(`^${token.markup[0]}{${token.markup.length},}\\s*$`).test(last) }
        }
    }
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
        Linking.openURL(resolved).catch(() => undefined)
    }
    // false stops the library from opening the unresolved URL itself.
    return false
}

/** A snapshot can end right after a list marker, which would render as an empty bullet until the next one. */
const TRAILING_LIST_MARKER = /\n[ \t]*(?:[-*+]|\d+[.)])[ \t]*$/

interface ChatMarkdownProps {
    text: string
    streaming?: boolean
}

export function ChatMarkdown({ text, streaming = false }: ChatMarkdownProps): ReactElement {
    return (
        <Markdown markdownit={markdownIt} rules={rules} style={markdownStyles} onLinkPress={openLink}>
            {streaming ? text.replace(TRAILING_LIST_MARKER, '') : text}
        </Markdown>
    )
}

const code = {
    fontFamily: fonts.mono,
    color: colors.ink,
} as const

const markdownStyles = StyleSheet.create({
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
