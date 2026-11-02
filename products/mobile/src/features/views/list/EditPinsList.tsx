import { type ReactElement, useCallback, useEffect, useMemo, useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'
import { Gesture, GestureDetector, ScrollView } from 'react-native-gesture-handler'
import Animated, {
    type SharedValue,
    useAnimatedReaction,
    useAnimatedStyle,
    useSharedValue,
    withTiming,
} from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'

import { haptic } from '@/lib/haptics'
import type { PinDisplayMode, PinView } from '@/model/views'
import { Eyebrow } from '@/ui/Eyebrow'
import { GripIcon } from '@/ui/icons/GripIcon'
import { MinusIcon } from '@/ui/icons/MinusIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { layout, motion, radii, type } from '@/ui/tokens'

import { pinModes } from '../pinHooks'
import { ModeSegment } from './ModeSegment'
import { ViewIcon, viewTypeLabel } from './viewMeta'

const ROW_HEIGHT = 56
const ROW_GAP = 8
const STEP = ROW_HEIGHT + ROW_GAP

type Positions = Record<string, number>

function positionsOf(ids: readonly string[]): Positions {
    return Object.fromEntries(ids.map((id, index) => [id, index]))
}

function orderOf(positions: Positions): string[] {
    return Object.keys(positions).sort((a, b) => (positions[a] ?? 0) - (positions[b] ?? 0))
}

interface EditPinsListProps {
    pins: readonly PinView[]
    contentTop: number
    contentBottom: number
    onReorder: (shortcutIds: string[]) => void
    onMove: (pin: PinView, direction: -1 | 1) => void
    onMode: (pin: PinView, mode: PinDisplayMode) => void
    onRemove: (pin: PinView) => void
}

/** "Edit pins": drag a handle to reorder, set each pin's mode, or remove it. Every change saves on this phone. */
export function EditPinsList({
    pins,
    contentTop,
    contentBottom,
    onReorder,
    onMove,
    onMode,
    onRemove,
}: EditPinsListProps): ReactElement {
    const styles = useStyles()
    const ids = useMemo(() => pins.map((pin) => pin.shortcutId), [pins])
    const idsKey = ids.join('|')
    const positions = useSharedValue<Positions>(positionsOf(ids))
    // biome-ignore lint/correctness/useExhaustiveDependencies: `idsKey` stands for `ids`.
    useEffect(() => {
        positions.value = positionsOf(ids)
    }, [idsKey, positions])
    const [scrollEnabled, setScrollEnabled] = useState(true)
    const commit = useCallback(() => {
        const next = orderOf(positions.value)
        if (next.some((id, index) => id !== ids[index])) {
            onReorder(next)
        }
    }, [positions, ids, onReorder])

    return (
        <ScrollView
            scrollEnabled={scrollEnabled}
            contentContainerStyle={[styles.content, { paddingTop: contentTop, paddingBottom: contentBottom }]}
            testID="edit-pins-sheet"
        >
            <View style={styles.sectionHeader}>
                <Eyebrow>Pinned</Eyebrow>
            </View>
            <View style={{ height: Math.max(0, pins.length * STEP - ROW_GAP) }}>
                {pins.map((pin, index) => (
                    <EditRow
                        key={pin.shortcutId}
                        pin={pin}
                        index={index}
                        count={pins.length}
                        positions={positions}
                        onDragState={setScrollEnabled}
                        onDrop={commit}
                        onMove={onMove}
                        onMode={onMode}
                        onRemove={onRemove}
                    />
                ))}
            </View>
            <Text style={styles.note}>
                Drag a handle to reorder. The toggle sets how each pin shows: as a row, a number or a chart.
            </Text>
        </ScrollView>
    )
}

interface EditRowProps {
    pin: PinView
    index: number
    count: number
    positions: SharedValue<Positions>
    onDragState: (scrollEnabled: boolean) => void
    onDrop: () => void
    onMove: EditPinsListProps['onMove']
    onMode: EditPinsListProps['onMode']
    onRemove: EditPinsListProps['onRemove']
}

function EditRow({
    pin,
    index,
    count,
    positions,
    onDragState,
    onDrop,
    onMove,
    onMode,
    onRemove,
}: EditRowProps): ReactElement {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const id = pin.shortcutId
    const top = useSharedValue(index * STEP)
    const dragging = useSharedValue(false)
    const start = useSharedValue(0)

    // Rows that make room for the dragged one slide to their new slot.
    useAnimatedReaction(
        () => positions.value[id] ?? 0,
        (position, previous) => {
            if (position !== previous && !dragging.value) {
                top.value = withTiming(position * STEP, { duration: motion.fade })
            }
        }
    )

    const pan = Gesture.Pan()
        .minDistance(0)
        .onStart(() => {
            dragging.value = true
            start.value = (positions.value[id] ?? 0) * STEP
            scheduleOnRN(onDragState, false)
            scheduleOnRN(haptic, 'light')
        })
        .onUpdate((event) => {
            const max = (count - 1) * STEP
            const y = Math.min(Math.max(start.value + event.translationY, 0), max)
            top.value = y
            const from = positions.value[id] ?? 0
            const to = Math.min(Math.max(Math.round(y / STEP), 0), count - 1)
            if (to === from) {
                return
            }
            const next: Positions = { ...positions.value }
            for (const other of Object.keys(next)) {
                if (next[other] === to) {
                    next[other] = from
                }
            }
            next[id] = to
            positions.value = next
            scheduleOnRN(haptic, 'selection')
        })
        .onFinalize(() => {
            if (!dragging.value) {
                return
            }
            dragging.value = false
            top.value = withTiming((positions.value[id] ?? 0) * STEP, { duration: motion.fade })
            scheduleOnRN(onDragState, true)
            scheduleOnRN(onDrop)
        })

    const rowStyle = useAnimatedStyle(() => ({
        transform: [{ translateY: top.value }],
        zIndex: dragging.value ? 2 : 1,
    }))
    const liftStyle = useAnimatedStyle(() => ({ opacity: dragging.value ? 1 : 0 }))

    const modes = pinModes(pin)
    const key = `${pin.kind}-${pin.ref ?? pin.kind}`
    return (
        <Animated.View style={[styles.rowSlot, rowStyle]}>
            <Animated.View style={[StyleSheet.absoluteFill, styles.lift, shadows.card, liftStyle]} />
            <View style={styles.row} testID={`edit-pin-${key}`}>
                <Pressable44
                    onPress={() => onRemove(pin)}
                    accessibilityLabel={`Unpin ${pin.name}`}
                    hitSlop={9}
                    haptic="light"
                    style={styles.remove}
                    testID={`edit-pin-remove-${key}`}
                >
                    {/* White on the red remove control in both schemes, like the iOS delete control. */}
                    <MinusIcon size={14} color={colors.white} />
                </Pressable44>
                <View style={styles.iconTile}>
                    <ViewIcon kind={pin.kind} size={16} />
                </View>
                <View style={styles.text}>
                    <Text style={styles.title} numberOfLines={1}>
                        {pin.name}
                    </Text>
                    <Text style={styles.meta} numberOfLines={1}>
                        {viewTypeLabel(pin.kind) ?? 'Opens on the web'}
                    </Text>
                </View>
                <ModeSegment
                    value={pin.display.mode}
                    available={modes}
                    onChange={(mode) => onMode(pin, mode)}
                    variant="icons"
                    name={pin.name}
                    testIDFor={(mode) => `edit-pin-mode-${mode}-${key}`}
                />
                <GestureDetector gesture={pan}>
                    <View
                        style={styles.handle}
                        accessible
                        accessibilityRole="adjustable"
                        accessibilityLabel={`Move ${pin.name}`}
                        accessibilityValue={{ text: `${index + 1} of ${count}` }}
                        accessibilityActions={[
                            { name: 'decrement', label: 'Move down' },
                            { name: 'increment', label: 'Move up' },
                        ]}
                        onAccessibilityAction={(event) => {
                            onMove(pin, event.nativeEvent.actionName === 'increment' ? -1 : 1)
                        }}
                        testID={`edit-pin-handle-${key}`}
                    >
                        <GripIcon size={20} color={colors.tertiary} />
                    </View>
                </GestureDetector>
            </View>
        </Animated.View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: {
        paddingHorizontal: layout.inboxGutter,
    },
    sectionHeader: {
        minHeight: 28,
        justifyContent: 'center',
        marginTop: 18,
        marginBottom: 8,
        marginHorizontal: 4,
    },
    rowSlot: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: ROW_HEIGHT,
    },
    lift: {
        borderRadius: radii.option,
        backgroundColor: colors.surface,
    },
    row: {
        height: ROW_HEIGHT,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingLeft: 10,
        paddingRight: 4,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    remove: {
        width: 26,
        height: 26,
        borderRadius: 13,
        backgroundColor: colors.diffRed,
        alignItems: 'center',
        justifyContent: 'center',
    },
    iconTile: {
        width: 30,
        height: 30,
        borderRadius: radii.markLarge,
        backgroundColor: colors.sunken,
        alignItems: 'center',
        justifyContent: 'center',
    },
    text: {
        flex: 1,
        minWidth: 0,
    },
    title: {
        ...type.bodySmallStrong,
        lineHeight: 19,
        color: colors.ink,
    },
    meta: {
        ...type.meta,
        fontWeight: '600',
        color: colors.tertiary,
    },
    handle: {
        width: 44,
        height: 44,
        alignItems: 'center',
        justifyContent: 'center',
    },
    note: {
        ...type.meta,
        color: colors.tertiary,
        marginTop: 12,
        marginHorizontal: 4,
    },
}))
