import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { BackChip } from '@/ui/BackChip'
import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { MoreIcon } from '@/ui/icons/MoreIcon'
import { PillControl } from '@/ui/PillControl'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

const CHROME_TOP = 62
const CHROME_ROW_HEIGHT = 54
const CHROME_BOTTOM_PADDING = 18
/** Design-frame offset where the content starts at rest, below the chrome's blur fade. */
export const SESSION_CONTENT_TOP = CHROME_TOP + CHROME_ROW_HEIGHT + CHROME_BOTTOM_PADDING
const CHROME_SOLID = (CHROME_TOP + CHROME_ROW_HEIGHT) / (CHROME_TOP + CHROME_ROW_HEIGHT + CHROME_BOTTOM_PADDING)

interface SessionChromeProps {
    onBack: () => void
    /** "Open full replay". Absent on a list, and disabled in the demo. */
    onOpenFull?: (() => void) | null
    onMore?: (() => void) | null
}

export function SessionChrome({ onBack, onOpenFull, onMore }: SessionChromeProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    return (
        <View style={[fixed.chrome, { paddingTop: topOffset(insets, CHROME_TOP) }]}>
            <BlurEdge solid={CHROME_SOLID} />
            <FadeEdge direction="down" solid={CHROME_SOLID} opacity={layout.chromeTint} />
            <BackChip onPress={onBack} testID="replay-back" />
            <PillControl height={CHROME_ROW_HEIGHT}>
                {onOpenFull !== undefined ? (
                    <>
                        <Pressable44
                            onPress={() => onOpenFull?.()}
                            disabled={!onOpenFull}
                            accessibilityRole="link"
                            accessibilityLabel="Open full replay"
                            pressedBackground={colors.background}
                            style={styles.full}
                            testID="session-open-full"
                        >
                            <ExternalLinkIcon
                                size={iconSizes.control}
                                color={onOpenFull ? colors.ink : colors.disabled}
                            />
                            <Text style={[styles.fullText, !onOpenFull && styles.disabled]}>Open full replay</Text>
                        </Pressable44>
                        <View style={styles.divider} />
                    </>
                ) : null}
                <Pressable44
                    onPress={() => onMore?.()}
                    disabled={!onMore}
                    accessibilityLabel="More"
                    pressedBackground={colors.background}
                    style={styles.more}
                    testID="replay-more"
                >
                    <MoreIcon size={22} color={onMore ? colors.ink : colors.disabled} />
                </Pressable44>
            </PillControl>
        </View>
    )
}

const fixed = StyleSheet.create({
    chrome: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 20,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingHorizontal: layout.inboxGutter,
        paddingBottom: CHROME_BOTTOM_PADDING,
        pointerEvents: 'box-none',
    },
})

const useStyles = createStyles(({ colors }) => ({
    full: {
        height: 46,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingHorizontal: 12,
        borderRadius: 999,
    },
    fullText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    disabled: {
        color: colors.disabled,
    },
    divider: {
        width: 1,
        height: 24,
        backgroundColor: colors.hairline,
    },
    more: {
        width: 52,
        height: 46,
        borderRadius: 999,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
