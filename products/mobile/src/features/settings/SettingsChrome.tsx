import type { ReactElement } from 'react'
import { type LayoutChangeEvent, StyleSheet, View } from 'react-native'
import Animated, {
    Extrapolation,
    interpolate,
    type SharedValue,
    useAnimatedStyle,
    useReducedMotion,
    useSharedValue,
} from 'react-native-reanimated'

import { BackChip } from '@/ui/BackChip'
import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { colors, layout, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { collapsingTitleTransform, type TitleGeometry } from './collapsingTitle'

export const SETTINGS_CHROME_TOP = 58
export const SETTINGS_CHROME_ROW_HEIGHT = 46
export const SETTINGS_TITLE_GAP = 20
const CHROME_BOTTOM_PADDING = 10
const CHROME_SOLID = 0.7
const TITLE_CHIP_GAP = 12

const TITLE_LINE_HEIGHT = type.screenTitle.lineHeight ?? 0
const TITLE_END_SCALE = (type.sectionHeader.fontSize ?? 17) / (type.screenTitle.fontSize ?? 28)
/** Rise from the large title's rest center to the chip row center. */
const TITLE_TRAVEL = SETTINGS_CHROME_ROW_HEIGHT / 2 + SETTINGS_TITLE_GAP + TITLE_LINE_HEIGHT / 2
/** Scroll offset at which the large title's bottom passes under the chrome's bottom edge. */
const TITLE_UNDER_CHROME = SETTINGS_TITLE_GAP + TITLE_LINE_HEIGHT - CHROME_BOTTOM_PADDING
const REDUCED_MOTION_REVEAL_DISTANCE = 28

interface SettingsChromeProps {
    title: string
    scrollY: SharedValue<number>
    onBack: () => void
}

export function SettingsChrome({ title, scrollY, onBack }: SettingsChromeProps): ReactElement {
    const insets = useScreenInsets()
    const reduceMotion = useReducedMotion()
    const chipWidth = useSharedValue(0)
    const onChipLayout = (event: LayoutChangeEvent): void => {
        chipWidth.value = event.nativeEvent.layout.width
    }

    const titleStyle = useAnimatedStyle(() => {
        const geometry: TitleGeometry = {
            travel: TITLE_TRAVEL,
            shift: chipWidth.value + TITLE_CHIP_GAP,
            endScale: TITLE_END_SCALE,
            gap: SETTINGS_TITLE_GAP,
            halfHeight: TITLE_LINE_HEIGHT / 2,
        }
        if (reduceMotion) {
            const end = collapsingTitleTransform(TITLE_TRAVEL, geometry)
            const start = Math.max(0, TITLE_UNDER_CHROME - REDUCED_MOTION_REVEAL_DISTANCE)
            return {
                opacity:
                    chipWidth.value > 0
                        ? interpolate(scrollY.value, [start, TITLE_UNDER_CHROME], [0, 1], Extrapolation.CLAMP)
                        : 0,
                transform: [{ translateX: end.translateX }, { translateY: end.translateY }, { scale: end.scale }],
            }
        }
        const t = collapsingTitleTransform(scrollY.value, geometry)
        return {
            // Until the chip is measured the shift is unknown, so a moving title could land on the chip.
            opacity: chipWidth.value > 0 || t.translateY === 0 ? 1 : 0,
            transform: [{ translateX: t.translateX }, { translateY: t.translateY }, { scale: t.scale }],
        }
    })

    const chromeTop = topOffset(insets, SETTINGS_CHROME_TOP)
    return (
        <View style={[styles.chrome, { paddingTop: chromeTop }]}>
            <BlurEdge solid={CHROME_SOLID} />
            <FadeEdge direction="down" solid={CHROME_SOLID} opacity={layout.chromeTint} />
            <View onLayout={onChipLayout}>
                <BackChip onPress={onBack} testID="settings-back" />
            </View>
            {/* The title rests below the chrome's bounds; it still draws there because overflow is visible and it takes no touches. */}
            <Animated.Text
                style={[styles.title, { top: chromeTop + SETTINGS_CHROME_ROW_HEIGHT + SETTINGS_TITLE_GAP }, titleStyle]}
                numberOfLines={1}
                accessibilityElementsHidden
                importantForAccessibility="no-hide-descendants"
                testID="settings-chrome-title"
            >
                {title}
            </Animated.Text>
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
        paddingHorizontal: layout.detailGutter,
        paddingBottom: CHROME_BOTTOM_PADDING,
        overflow: 'visible',
        pointerEvents: 'box-none',
    },
    title: {
        ...type.screenTitle,
        position: 'absolute',
        left: layout.detailGutter,
        color: colors.ink,
        transformOrigin: 'left center',
        pointerEvents: 'none',
    },
})
