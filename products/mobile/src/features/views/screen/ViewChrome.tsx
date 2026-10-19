import type { ReactElement } from 'react'
import { StyleSheet, View } from 'react-native'

import { BackChip } from '@/ui/BackChip'
import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { MoreIcon } from '@/ui/icons/MoreIcon'
import { PillControl } from '@/ui/PillControl'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, layout } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

const CHROME_TOP = 62
const CHROME_ROW_HEIGHT = 54
const CHROME_BOTTOM_PADDING = 18
/** Design-frame offset where a view's content starts at rest, below the chrome's blur fade. */
export const VIEW_CONTENT_TOP = CHROME_TOP + CHROME_ROW_HEIGHT + CHROME_BOTTOM_PADDING + 8
const CHROME_SOLID = (CHROME_TOP + CHROME_ROW_HEIGHT) / (CHROME_TOP + CHROME_ROW_HEIGHT + CHROME_BOTTOM_PADDING)

interface ViewChromeProps {
    onBack: () => void
    /** "Open on web" and the other view actions. */
    onMore?: () => void
}

/** The floating top row of a dashboard, insight or web analytics screen: Back, then More. */
export function ViewChrome({ onBack, onMore }: ViewChromeProps): ReactElement {
    const insets = useScreenInsets()
    return (
        <View style={[styles.chrome, { paddingTop: topOffset(insets, CHROME_TOP) }]}>
            <BlurEdge solid={CHROME_SOLID} />
            <FadeEdge direction="down" solid={CHROME_SOLID} opacity={layout.chromeTint} />
            <BackChip onPress={onBack} testID="view-back" />
            <PillControl height={CHROME_ROW_HEIGHT}>
                <Pressable44
                    onPress={() => onMore?.()}
                    disabled={!onMore}
                    accessibilityLabel="More"
                    pressedBackground={colors.background}
                    style={styles.button}
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
        paddingBottom: CHROME_BOTTOM_PADDING,
        pointerEvents: 'box-none',
    },
    button: {
        width: 56,
        height: 46,
        borderRadius: 999,
        alignItems: 'center',
        justifyContent: 'center',
    },
})
