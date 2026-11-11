import type { ReactElement } from 'react'
import { Linking, StyleSheet, Text, View } from 'react-native'

import { safeHttpsUrl } from '@/lib/urls'
import { Eyebrow } from '@/ui/Eyebrow'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { trackWebTileOpened, type WebTileLink } from './analytics'

const LINKS: readonly { tile: WebTileLink; title: string }[] = [
    { tile: 'goals', title: 'Goals' },
    { tile: 'web_vitals', title: 'Web vitals' },
    { tile: 'error_tracking', title: 'Error tracking' },
    { tile: 'session_replay', title: 'Session replay' },
    { tile: 'frustrating_pages', title: 'Frustrating pages' },
]

export function MoreOnWeb({ webUrl }: { webUrl: string | undefined }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const safe = webUrl ? safeHttpsUrl(webUrl) : undefined
    return (
        <View style={styles.section} testID="web-more-on-web">
            <Eyebrow>More on web</Eyebrow>
            <View style={styles.group}>
                {LINKS.map((link, index) => (
                    <Pressable44
                        key={link.tile}
                        onPress={() => {
                            if (!safe) {
                                return
                            }
                            trackWebTileOpened({ tile: link.tile })
                            Linking.openURL(safe).catch(() => undefined)
                        }}
                        disabled={!safe}
                        hitSlop={0}
                        accessibilityRole="link"
                        accessibilityLabel={safe ? `${link.title}, opens on the web` : link.title}
                        accessibilityHint={webUrl ? undefined : 'Not available in the demo.'}
                        pressedBackground={colors.pressed}
                        style={[styles.row, index > 0 && styles.divider]}
                        testID={`web-more-${link.tile}`}
                    >
                        <View style={styles.text}>
                            <Text style={[styles.title, !safe && styles.disabled]}>{link.title}</Text>
                            {webUrl ? null : <Text style={styles.meta}>Not available in the demo</Text>}
                        </View>
                        <ExternalLinkIcon size={16} color={safe ? colors.secondary : colors.disabled} />
                    </Pressable44>
                ))}
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    section: {
        gap: 8,
    },
    group: {
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    row: {
        minHeight: 48,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingHorizontal: 14,
        paddingVertical: 8,
        backgroundColor: colors.surface,
    },
    divider: {
        borderTopWidth: StyleSheet.hairlineWidth,
        borderTopColor: colors.rowDivider,
    },
    text: {
        flex: 1,
        minWidth: 0,
    },
    title: {
        ...type.body,
        color: colors.ink,
    },
    disabled: {
        color: colors.secondary,
    },
    meta: {
        ...type.meta,
        color: colors.tertiary,
    },
}))
