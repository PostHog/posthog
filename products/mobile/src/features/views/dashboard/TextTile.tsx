import type { ReactElement } from 'react'
import { Linking, Text, View } from 'react-native'
import Markdown, { MarkdownIt, type RenderRules } from 'react-native-markdown-display'

import { safeHttpsUrl } from '@/lib/urls'
import { createStyles } from '@/ui/theme'
import { fonts, radii, type } from '@/ui/tokens'

/** `html: false` renders raw HTML in a text card as text, so a card cannot inject markup. */
const markdownIt = MarkdownIt({ html: false, linkify: true, typographer: false })

const rules: RenderRules = {
    // Images in a text card load from any host, so the phone leaves them out.
    image: () => null,
}

function openLink(url: string): boolean {
    const safe = safeHttpsUrl(url)
    if (safe) {
        Linking.openURL(safe).catch(() => undefined)
    }
    // false stops the library from opening a link that is not https.
    return false
}

const HEADING_ONLY = /^\s*#{1,3}\s+([^\n]+?)\s*#*\s*$/

/**
 * A dashboard text card. A card that holds only one heading is how dashboards mark a section, so it shows as a
 * section header instead of a card.
 */
export function TextTile({ text, tileId }: { text: string | null; tileId: number }): ReactElement | null {
    const styles = useStyles()
    const markdownStyles = useMarkdownStyles()
    const body = text?.trim()
    if (!body) {
        return null
    }
    const heading = HEADING_ONLY.exec(body)?.[1]
    if (heading) {
        return (
            <Text style={styles.section} accessibilityRole="header" testID={`view-tile-${tileId}`}>
                {heading}
            </Text>
        )
    }
    return (
        <View style={styles.card} testID={`view-tile-${tileId}`}>
            <Markdown markdownit={markdownIt} rules={rules} style={markdownStyles} onLinkPress={openLink}>
                {body}
            </Markdown>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    section: {
        ...type.sectionHeader,
        color: colors.ink,
        paddingTop: 10,
        paddingHorizontal: 2,
    },
    card: {
        paddingHorizontal: 14,
        paddingTop: 12,
        paddingBottom: 2,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
}))

const useMarkdownStyles = createStyles(({ colors }) => ({
    body: {
        ...type.bodySmall,
        color: colors.ink,
    },
    paragraph: {
        marginTop: 0,
        marginBottom: 10,
    },
    heading1: { ...type.sheetTitle, marginTop: 0, marginBottom: 8 },
    heading2: { ...type.sectionHeader, marginTop: 0, marginBottom: 8 },
    heading3: { ...type.bodyStrong, marginTop: 0, marginBottom: 6 },
    link: {
        color: colors.blue,
        textDecorationLine: 'none',
    },
    code_inline: {
        fontFamily: fonts.mono,
        fontSize: 13,
        backgroundColor: colors.sunken,
    },
    bullet_list: {
        marginBottom: 10,
    },
    ordered_list: {
        marginBottom: 10,
    },
}))
