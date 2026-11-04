import { type ReactElement, type ReactNode, useState } from 'react'
import { View } from 'react-native'
import Animated, { useAnimatedStyle } from 'react-native-reanimated'

import { BackChip } from './BackChip'
import { BlurEdge } from './BlurEdge'
import { FadeEdge } from './FadeEdge'
import { screenLayout } from './screenLayout'
import { scrollTitleOpacity } from './scrollTitleOpacity'
import { createStyles } from './theme'
import { layout, type } from './tokens'
import { topOffset, useScreenInsets } from './useScreenInsets'
import type { ScrollTitle } from './useScrollTitle'

interface ScreenChromeProps {
    onBack: () => void
    backTestID: string
    title?: ScrollTitle
    right?: ReactNode
}

export function ScreenChrome({ onBack, backTestID, title, right }: ScreenChromeProps): ReactElement {
    const styles = useStyles()
    const insets = useScreenInsets()
    const [leftWidth, setLeftWidth] = useState(0)
    const [rightWidth, setRightWidth] = useState(0)
    const top = topOffset(insets, screenLayout.top)
    const sideInset = layout.detailGutter + Math.max(leftWidth, rightWidth) + 8
    const solid = (top + screenLayout.rowHeight) / (top + screenLayout.rowHeight + screenLayout.bottomPadding)
    const titleStyle = useAnimatedStyle(() => ({
        opacity: title ? scrollTitleOpacity(title.scrollY.value, title.revealEnd) : 0,
    }))
    return (
        <View style={[styles.chrome, { paddingTop: top }]}>
            <BlurEdge solid={solid} />
            <FadeEdge direction="down" solid={solid} opacity={layout.chromeTint} />
            <View onLayout={(event) => setLeftWidth(event.nativeEvent.layout.width)}>
                <BackChip onPress={onBack} testID={backTestID} />
            </View>
            <View onLayout={(event) => setRightWidth(event.nativeEvent.layout.width)}>{right}</View>
            <Animated.View
                style={[styles.titleSlot, { top, left: sideInset, right: sideInset }, titleStyle]}
                pointerEvents="none"
                accessibilityElementsHidden
                importantForAccessibility="no-hide-descendants"
                aria-hidden
                testID="screen-chrome-title"
            >
                <Animated.Text style={styles.title} numberOfLines={1}>
                    {title?.text}
                </Animated.Text>
            </Animated.View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    chrome: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 20,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingHorizontal: layout.detailGutter,
        paddingBottom: screenLayout.bottomPadding,
        pointerEvents: 'box-none',
    },
    titleSlot: {
        position: 'absolute',
        height: screenLayout.rowHeight,
        justifyContent: 'center',
    },
    title: {
        ...type.sectionHeader,
        color: colors.ink,
        textAlign: 'center',
    },
}))
