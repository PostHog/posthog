import { type ReactElement, useState } from 'react'
import { type AccessibilityActionEvent, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated'

import { serverNow } from '@/api/serverClock'
import type { ResolvedRange } from '@/model/views'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'
import type { RangeSheetEntry } from '../analytics'
import { projectToday, type StepContext, type StepDirection } from '../rangeStep'
import type { ViewRange } from '../rangeStore'
import { type RangeCompareRow, RangeSheet } from './RangeSheet'

/** A swipe on the range button steps once it travels this far. */
const SWIPE_STEP = 28
/** How far the button follows the finger, so the swipe feels attached without leaving the row. */
const SWIPE_FOLLOW = 28

const EMPTY_LABEL = "Each tile's own range"

interface ViewRangeControlProps {
    range: ViewRange
    /** The window the server resolved for the range on screen. Steps start from it. */
    resolved: ResolvedRange | null
    /** True while the screen still shows the previous range. Steps wait for the new window. */
    loading?: boolean
    /** The resolved dates under the control, which the sheet repeats. */
    detail: string | null
    /**
     * Another server time with the project's UTC offset, such as the resolved end of a tile with its own range. The
     * calendar takes the project's today from it while the range on screen has no resolved window.
     */
    zoneHint?: string | null
    /** Null leaves the compare row out of the sheet. */
    compare: RangeCompareRow | null
}

function stepContext(resolved: ResolvedRange | null): StepContext {
    const now = serverNow()
    return { resolved, today: projectToday(resolved?.to ?? null, now), now }
}

export function ViewRangeControl({
    range,
    resolved,
    loading = false,
    detail,
    compare,
    zoneHint = null,
}: ViewRangeControlProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const [open, setOpen] = useState(false)
    const [pressed, setPressed] = useState(false)
    const offset = useSharedValue(0)
    const steppable = loading ? null : resolved
    const context = stepContext(steppable)
    const canPrev = range.canStep(-1, context)
    const canNext = range.canStep(1, context)
    const today = projectToday(resolved?.to ?? zoneHint, context.now)
    const label = range.label ?? EMPTY_LABEL

    const step = (direction: StepDirection): void => {
        range.step(direction, stepContext(steppable))
    }
    const openSheet = (entry: RangeSheetEntry): void => {
        setOpen(true)
        range.noteSheetOpened(entry)
    }

    const tap = Gesture.Tap()
        .runOnJS(true)
        .maxDistance(10)
        .onBegin(() => setPressed(true))
        .onFinalize(() => setPressed(false))
        .onEnd((_event, success) => {
            if (success) {
                openSheet('button')
            }
        })
    const swipe = Gesture.Pan()
        .runOnJS(true)
        .activeOffsetX([-8, 8])
        .failOffsetY([-10, 10])
        .onUpdate((event) => {
            offset.value = Math.max(-SWIPE_FOLLOW, Math.min(SWIPE_FOLLOW, event.translationX * 0.5))
        })
        .onEnd((event) => {
            // A swipe to the right brings in the earlier period, like turning back a page.
            const direction: StepDirection = event.translationX > 0 ? -1 : 1
            if (Math.abs(event.translationX) > SWIPE_STEP && (direction < 0 ? canPrev : canNext)) {
                step(direction)
            }
        })
        .onFinalize(() => {
            offset.value = withTiming(0, { duration: 180 })
        })
    const buttonStyle = useAnimatedStyle(() => ({ transform: [{ translateX: offset.value }] }))

    const onAccessibilityAction = (event: AccessibilityActionEvent): void => {
        switch (event.nativeEvent.actionName) {
            case 'activate':
                openSheet('accessibility')
                break
            case 'increment':
                if (canNext) {
                    step(1)
                }
                break
            case 'decrement':
                if (canPrev) {
                    step(-1)
                }
                break
        }
    }

    return (
        <View style={styles.row}>
            <GestureDetector gesture={Gesture.Race(swipe, tap)}>
                <Animated.View
                    style={[styles.button, pressed && styles.buttonPressed, buttonStyle]}
                    accessible
                    accessibilityRole="adjustable"
                    accessibilityLabel="Date range"
                    accessibilityValue={{ text: label }}
                    accessibilityHint="Opens more ranges. Swipe up or down to change the period."
                    accessibilityActions={[{ name: 'activate' }, { name: 'increment' }, { name: 'decrement' }]}
                    onAccessibilityAction={onAccessibilityAction}
                    testID="view-range"
                >
                    <Text style={styles.label} numberOfLines={1}>
                        {label}
                    </Text>
                    <ChevronDownIcon size={14} color={colors.ink} />
                </Animated.View>
            </GestureDetector>
            <RangeSheet
                visible={open}
                onClose={() => setOpen(false)}
                range={range}
                emptyLabel={EMPTY_LABEL}
                detail={detail}
                today={today}
                compare={compare}
            />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 6,
        marginTop: 14,
    },
    button: {
        height: 40,
        maxWidth: '100%',
        flexShrink: 1,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingLeft: 16,
        paddingRight: 14,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    buttonPressed: {
        backgroundColor: colors.pressed,
    },
    label: {
        ...type.buttonSmall,
        color: colors.ink,
        flexShrink: 1,
    },
}))
