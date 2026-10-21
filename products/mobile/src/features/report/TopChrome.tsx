import type { ReactElement } from 'react'
import { ActivityIndicator, View } from 'react-native'
import Animated, {
    Extrapolation,
    FadeIn,
    FadeOut,
    interpolate,
    type SharedValue,
    useAnimatedStyle,
} from 'react-native-reanimated'

import { BackChip } from '@/ui/BackChip'
import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, motion, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

const CHROME_TOP = 58
const CHROME_ROW_HEIGHT = 46
const CHROME_BOTTOM_PADDING = 10
/** Design-frame offset of the chrome's bottom edge, so the scroll view can tell when the headline passes under it. */
export const TOP_CHROME_BOTTOM = CHROME_TOP + CHROME_ROW_HEIGHT + CHROME_BOTTOM_PADDING
/** Design-frame top padding of the content under the chrome. */
export const CONTENT_TOP = 116
/** The gap between the chrome and the headline at rest, so the title reveal ends as the headline fully passes under. */
export const HEADLINE_GAP = CONTENT_TOP - TOP_CHROME_BOTTOM
const CHROME_SOLID = 0.7

/** How far the headline rises before the chrome title is fully visible. */
const TITLE_REVEAL_DISTANCE = 28
const TITLE_REVEAL_RISE = 8

export interface ChromeTitle {
    text: string
    scrollY: SharedValue<number>
    /** Scroll offset at which the headline has fully passed under the chrome. Zero until it is measured. */
    revealEnd: number
}

interface TopChromeProps {
    onBack: () => void
    onPrevious?: () => void
    onNext?: () => void
    title?: ChromeTitle
    refreshing?: boolean
    /** False leaves out the Previous and Next pill, for a screen that is not one report of the inbox list. */
    withPager?: boolean
}

export function TopChrome({
    onBack,
    onPrevious,
    onNext,
    title,
    refreshing = false,
    withPager = true,
}: TopChromeProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const insets = useScreenInsets()
    return (
        <View style={[styles.chrome, { paddingTop: topOffset(insets, CHROME_TOP) }]}>
            <BlurEdge solid={CHROME_SOLID} />
            <FadeEdge direction="down" solid={CHROME_SOLID} opacity={layout.chromeTint} />
            <BackChip onPress={onBack} testID="report-back" />
            <View style={styles.titleSlot}>{title ? <ScrollTitle title={title} /> : null}</View>
            <View style={styles.refreshSlot}>
                {refreshing ? (
                    <Animated.View entering={FadeIn.duration(motion.fade)} exiting={FadeOut.duration(motion.fade)}>
                        <ActivityIndicator
                            size="small"
                            color={colors.muted}
                            accessibilityLabel="Refreshing report"
                            testID="report-refreshing"
                        />
                    </Animated.View>
                ) : null}
            </View>
            {withPager ? (
                <SegmentedPill
                    height={CHROME_ROW_HEIGHT}
                    raised
                    segmentWidth={44}
                    segments={[
                        {
                            key: 'previous',
                            accessibilityLabel: 'Previous report',
                            onPress: () => onPrevious?.(),
                            disabled: !onPrevious,
                            testID: 'report-previous',
                            children: <ChevronLeftIcon size={iconSizes.control} />,
                        },
                        {
                            key: 'next',
                            accessibilityLabel: 'Next report',
                            onPress: () => onNext?.(),
                            disabled: !onNext,
                            testID: 'report-next',
                            children: <ChevronRightIcon size={iconSizes.control} />,
                        },
                    ]}
                />
            ) : null}
        </View>
    )
}

function ScrollTitle({ title }: { title: ChromeTitle }): ReactElement {
    const styles = useStyles()
    const { scrollY, revealEnd } = title
    const animatedStyle = useAnimatedStyle(() => {
        if (revealEnd <= 0) {
            return { opacity: 0 }
        }
        const start = Math.max(0, revealEnd - TITLE_REVEAL_DISTANCE)
        const progress = interpolate(scrollY.value, [start, revealEnd], [0, 1], Extrapolation.CLAMP)
        return {
            opacity: progress,
            transform: [{ translateY: TITLE_REVEAL_RISE * (1 - progress) }],
        }
    })
    // The headline in the content is the accessible header, so the chrome copy stays out of the accessibility tree.
    return (
        <Animated.Text
            style={[styles.title, animatedStyle]}
            numberOfLines={1}
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            testID="report-chrome-title"
        >
            {title.text}
        </Animated.Text>
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
        paddingBottom: CHROME_BOTTOM_PADDING,
        pointerEvents: 'box-none',
    },
    titleSlot: {
        flex: 1,
        alignItems: 'center',
        paddingHorizontal: 10,
        pointerEvents: 'none',
    },
    refreshSlot: {
        width: 20,
        height: 20,
        marginRight: 8,
        alignItems: 'center',
        justifyContent: 'center',
        pointerEvents: 'none',
    },
    title: {
        ...type.sectionHeader,
        color: colors.ink,
        textAlign: 'center',
    },
}))
