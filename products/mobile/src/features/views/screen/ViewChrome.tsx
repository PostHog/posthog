import type { ReactElement } from 'react'
import { StyleSheet, View } from 'react-native'

import { BackChip } from '@/ui/BackChip'
import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { MoreIcon } from '@/ui/icons/MoreIcon'
import { PillControl } from '@/ui/PillControl'
import { Pressable44 } from '@/ui/Pressable44'
import { useColors } from '@/ui/theme'
import { layout } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

const DEFAULT_CHROME = { top: 62, rowHeight: 54, bottomPadding: 18, titleGap: 26 }
const COMPACT_CHROME = { top: 58, rowHeight: 46, bottomPadding: 10, titleGap: 20 }
/** Design-frame offset where a view's content starts at rest, below the chrome's blur fade. */
export const VIEW_CONTENT_TOP = DEFAULT_CHROME.top + DEFAULT_CHROME.rowHeight + DEFAULT_CHROME.titleGap
export const COMPACT_VIEW_CONTENT_TOP = COMPACT_CHROME.top + COMPACT_CHROME.rowHeight + COMPACT_CHROME.titleGap

interface ViewChromeProps {
    onBack: () => void
    /** "Open on web" and the other view actions. */
    onMore?: () => void
    compact?: boolean
}

/** The floating top row of a dashboard, insight or web analytics screen: Back, then More. */
export function ViewChrome({ onBack, onMore, compact = false }: ViewChromeProps): ReactElement {
    const colors = useColors()
    const insets = useScreenInsets()
    const chrome = compact ? COMPACT_CHROME : DEFAULT_CHROME
    const solid = (chrome.top + chrome.rowHeight) / (chrome.top + chrome.rowHeight + chrome.bottomPadding)
    return (
        <View
            style={[styles.chrome, { paddingTop: topOffset(insets, chrome.top), paddingBottom: chrome.bottomPadding }]}
        >
            <BlurEdge solid={solid} />
            <FadeEdge direction="down" solid={solid} opacity={layout.chromeTint} />
            <BackChip onPress={onBack} testID="view-back" />
            <PillControl height={chrome.rowHeight}>
                <Pressable44
                    onPress={() => onMore?.()}
                    disabled={!onMore}
                    accessibilityLabel="More"
                    pressedBackground={colors.background}
                    style={[styles.button, compact && styles.compactButton]}
                    testID="view-more"
                >
                    <MoreIcon size={22} color={onMore ? colors.ink : colors.disabled} />
                </Pressable44>
            </PillControl>
        </View>
    )
}

const styles = StyleSheet.create({
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
        pointerEvents: 'box-none',
    },
    button: {
        width: 56,
        height: 46,
        borderRadius: 999,
        alignItems: 'center',
        justifyContent: 'center',
    },
    compactButton: {
        height: 36,
    },
})
