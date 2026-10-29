import type { ReactElement } from 'react'
import type { TextStyle, ViewStyle } from 'react-native'
import Markdown, { type RenderRules } from 'react-native-markdown-display'

import { createMarkdownIt } from '@/lib/markdownIt'
import { createStyles, type Theme } from '@/ui/theme'
import { fonts, type } from '@/ui/tokens'

import { chartRefsPlugin } from './chartRefs'
import { MonoBlock } from './MonoBlock'
import { openDetailsLink } from './openDetailsLink'

const markdownIt = createMarkdownIt().use(chartRefsPlugin)

// The parser keeps a trailing newline on a fenced block, which would add an empty line at the end of the card.
function withoutTrailingNewline(code: string): string {
    return code.endsWith('\n') ? code.slice(0, -1) : code
}

const rules: RenderRules = {
    // Remote images would load from any host, so the full report drops them.
    image: () => null,
    fence: (node) => <MonoBlock key={node.key} code={withoutTrailingNewline(node.content)} />,
    code_block: (node) => <MonoBlock key={node.key} code={withoutTrailingNewline(node.content)} />,
}

interface ReportMarkdownProps {
    text: string
    reportId: string
    /** `summary` is the report's own text at body size; `signal` is a signal's content inside its card. */
    tone: 'summary' | 'signal'
}

export function ReportMarkdown({ text, reportId, tone }: ReportMarkdownProps): ReactElement {
    const summaryStyles = useSummaryStyles()
    const signalStyles = useSignalStyles()
    const openLink = (url: string): boolean => {
        openDetailsLink(url, reportId, 'link')
        // false stops the library from opening the URL itself, because openDetailsLink opens only https links.
        return false
    }
    return (
        <Markdown
            markdownit={markdownIt}
            rules={rules}
            style={tone === 'summary' ? summaryStyles : signalStyles}
            onLinkPress={openLink}
        >
            {text}
        </Markdown>
    )
}

function summaryStylesFor({ colors }: Theme) {
    const code = {
        fontFamily: fonts.mono,
        color: colors.ink,
    } as const
    const heading = { ...type.sectionHeader, color: colors.ink, marginTop: 8, marginBottom: 6 } as const
    return {
        body: {
            ...type.body,
            color: colors.ink,
        },
        paragraph: {
            marginTop: 0,
            marginBottom: 12,
        },
        heading1: heading,
        heading2: heading,
        heading3: { ...type.bodyStrong, color: colors.ink, marginTop: 10, marginBottom: 4 },
        heading4: { ...type.bodyStrong, color: colors.ink, marginTop: 10, marginBottom: 4 },
        heading5: { ...type.bodyStrong, color: colors.ink, marginTop: 10, marginBottom: 4 },
        heading6: { ...type.bodyStrong, color: colors.ink, marginTop: 10, marginBottom: 4 },
        strong: {
            fontWeight: '600',
        },
        link: {
            color: colors.ink,
            textDecorationLine: 'underline',
        },
        bullet_list: {
            marginBottom: 12,
        },
        ordered_list: {
            marginBottom: 12,
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
        blockquote: {
            backgroundColor: 'transparent',
            borderColor: colors.hairline,
            borderLeftWidth: 3,
            marginLeft: 0,
            paddingHorizontal: 12,
            paddingVertical: 0,
            marginBottom: 12,
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
            marginBottom: 12,
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
    } satisfies Record<string, TextStyle | ViewStyle>
}

const useSummaryStyles = createStyles(summaryStylesFor)

const useSignalStyles = createStyles((theme) => {
    const { colors } = theme
    const summaryStyles = summaryStylesFor(theme)
    const signalHeading = { ...type.bodySmallStrong, color: colors.ink, marginTop: 4, marginBottom: 4 } as const
    return {
        ...summaryStyles,
        body: {
            ...type.bodySmall,
            color: colors.ink,
        },
        paragraph: {
            marginTop: 0,
            marginBottom: 10,
        },
        heading1: signalHeading,
        heading2: signalHeading,
        heading3: signalHeading,
        heading4: signalHeading,
        heading5: signalHeading,
        heading6: signalHeading,
        code_inline: {
            ...summaryStyles.code_inline,
            fontSize: 13,
        },
    }
})
