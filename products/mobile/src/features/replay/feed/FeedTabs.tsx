import { type ReactElement, useState } from 'react'
import { type LayoutChangeEvent, Pressable, View } from 'react-native'
import Animated, { interpolate, type SharedValue, useAnimatedStyle } from 'react-native-reanimated'

import { createStyles } from '@/ui/theme'

import { FEED_TAB_LABELS, type FeedUnit } from './feedModel'
import { feedColors, feedTextShadow } from './feedStyle'

const UNITS: readonly FeedUnit[] = ['moment', 'session']
const UNDERLINE_WIDTH = 22
const INACTIVE_OPACITY = 0.6

interface FeedTabsProps {
    unit: FeedUnit
    /** 0 on Moment, 1 on Full recording. A sideways swipe on the video moves it with the finger. */
    progress: SharedValue<number>
    onSelect: (unit: FeedUnit) => void
}

/** The feed's mode as two text tabs. The highlight follows `progress`, so it tracks a swipe before the tab changes. */
export function FeedTabs({ unit, progress, onSelect }: FeedTabsProps): ReactElement {
    const styles = useStyles()
    const [centers, setCenters] = useState<[number, number] | null>(null)
    const onLayout = (index: number) => (event: LayoutChangeEvent) => {
        const { x, width } = event.nativeEvent.layout
        setCenters((previous) => {
            const next: [number, number] = previous ? [...previous] : [x + width / 2, x + width / 2]
            next[index] = x + width / 2
            return previous && previous[0] === next[0] && previous[1] === next[1] ? previous : next
        })
    }
    const underline = useAnimatedStyle(() => {
        if (!centers) {
            return { opacity: 0 }
        }
        return {
            opacity: 1,
            transform: [{ translateX: interpolate(progress.value, [0, 1], centers, 'clamp') - UNDERLINE_WIDTH / 2 }],
        }
    })
    const momentStyle = useAnimatedStyle(() => ({
        opacity: interpolate(progress.value, [0, 1], [1, INACTIVE_OPACITY], 'clamp'),
    }))
    const sessionStyle = useAnimatedStyle(() => ({
        opacity: interpolate(progress.value, [0, 1], [INACTIVE_OPACITY, 1], 'clamp'),
    }))
    return (
        <View style={styles.tabs} accessibilityRole="tablist">
            {UNITS.map((option, index) => {
                const selected = option === unit
                return (
                    <Pressable
                        key={option}
                        onPress={() => onSelect(option)}
                        onLayout={onLayout(index)}
                        accessibilityRole="tab"
                        accessibilityState={{ selected }}
                        accessibilityLabel={FEED_TAB_LABELS[option]}
                        hitSlop={{ top: 10, bottom: 10, left: 8, right: 8 }}
                        style={styles.tab}
                        testID={`feed-tab-${option}`}
                    >
                        <Animated.Text
                            style={[styles.label, selected && styles.labelOn, index === 0 ? momentStyle : sessionStyle]}
                            numberOfLines={1}
                        >
                            {FEED_TAB_LABELS[option]}
                        </Animated.Text>
                    </Pressable>
                )
            })}
            <Animated.View style={[styles.underline, underline]} pointerEvents="none" />
        </View>
    )
}

const useStyles = createStyles(() => ({
    tabs: {
        height: 44,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 20,
    },
    tab: {
        height: 44,
        justifyContent: 'center',
    },
    label: {
        fontSize: 16,
        fontWeight: '600',
        color: feedColors.text,
        ...feedTextShadow,
    },
    labelOn: {
        fontWeight: '800',
    },
    underline: {
        position: 'absolute',
        left: 0,
        bottom: 5,
        width: UNDERLINE_WIDTH,
        height: 3,
        borderRadius: 1.5,
        backgroundColor: feedColors.text,
    },
}))
