import { type ReactElement, useState } from 'react'
import { type AccessibilityActionEvent, StyleSheet, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated'

import { serverNow } from '@/api/serverClock'
import type { ResolvedRange } from '@/model/views'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, type } from '@/ui/tokens'
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

/**
 * The date range in a view header: ‹ and › step through periods, a swipe on the button does the same, and a tap opens
 * the range sheet. "Not saved" shows while the range differs from the one the view saved.
 */
export function ViewRangeControl({
    range,
    resolved,
    loading = false,
    detail,
    compare,
    zoneHint = null,
}: ViewRangeControlProps): ReactElement {
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
            <StepButton direction={-1} enabled={canPrev} onPress={() => step(-1)} />
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
            <StepButton direction={1} enabled={canNext} onPress={() => step(1)} />
            {range.isSaved ? null : (
                <Pressable44
                    onPress={() => openSheet('not_saved')}
                    accessibilityLabel="Not saved"
                    accessibilityHint="This range is not saved to the view. Opens the date range options."
                    pressedBackground={colors.pressed}
                    style={styles.notSaved}
                    testID="view-range-not-saved"
                >
                    <Text style={styles.notSavedText}>Not saved</Text>
                </Pressable44>
            )}
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

function StepButton({
    direction,
    enabled,
    onPress,
}: {
    direction: StepDirection
    enabled: boolean
    onPress: () => void
}): ReactElement {
    const Icon = direction < 0 ? ChevronLeftIcon : ChevronRightIcon
    return (
        <Pressable44
            onPress={onPress}
            disabled={!enabled}
            accessibilityLabel={direction < 0 ? 'Previous period' : 'Next period'}
            accessibilityState={{ disabled: !enabled }}
            pressedBackground={colors.pressed}
            style={[styles.step, !enabled && styles.stepDisabled]}
            testID={direction < 0 ? 'range-step-prev' : 'range-step-next'}
        >
            <Icon size={14} color={enabled ? colors.ink : colors.disabled} />
        </Pressable44>
    )
}

const styles = StyleSheet.create({
    row: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 6,
        marginTop: 14,
    },
    step: {
        width: 40,
        height: 40,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.white,
        alignItems: 'center',
        justifyContent: 'center',
    },
    stepDisabled: {
        borderColor: colors.hairline,
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
        backgroundColor: colors.white,
    },
    buttonPressed: {
        backgroundColor: colors.pressed,
    },
    label: {
        ...type.buttonSmall,
        color: colors.ink,
        flexShrink: 1,
    },
    notSaved: {
        height: 26,
        justifyContent: 'center',
        paddingHorizontal: 10,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
    },
    notSavedText: {
        fontSize: 12,
        fontWeight: '600',
        color: colors.secondary,
    },
})
