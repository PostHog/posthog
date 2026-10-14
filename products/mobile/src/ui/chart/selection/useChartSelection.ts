import { useCallback, useRef, useState } from 'react'
import { type SharedValue, useAnimatedReaction, useDerivedValue } from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'
import { type ChartPressState, useChartPressState } from 'victory-native'

import { haptic } from '@/lib/haptics'

import { snapToValue } from '../chartMath'
import type { ChartPoint } from '../types'

type PressState = ChartPressState<{ x: number; y: { value: number } }>

export interface ChartSelection {
    pressState: PressState
    /** The selected index on the UI thread, snapped to the nearest finite value. -1 = none. */
    selected: SharedValue<number>
    /** The JS mirror of `selected`, for the tooltip. */
    selectedIndex: number
    selectByTap: (index: number) => void
}

export function useChartSelection(
    points: ChartPoint[],
    values: number[],
    onSelect: ((point: ChartPoint | null) => void) | undefined
): ChartSelection {
    const [selectedIndex, setSelectedIndex] = useState(-1)
    const lastIndex = useRef(-1)
    // victory-native resets its press state when `data` changes; the JS mirror of it resets here, during render.
    const [selectionPoints, setSelectionPoints] = useState(points)
    if (selectionPoints !== points) {
        setSelectionPoints(points)
        setSelectedIndex(-1)
        lastIndex.current = -1
    }

    const { state } = useChartPressState({ x: 0, y: { value: 0 } })
    const selected = useDerivedValue(() => snapToValue(values, state.matchedIndex.value))

    const emitSelection = useCallback(
        (index: number, pressStarted: boolean): void => {
            const changed = index !== lastIndex.current
            lastIndex.current = index
            setSelectedIndex(index)
            const point = points[index]
            if (!point) {
                if (changed) {
                    onSelect?.(null)
                }
                return
            }
            if (changed) {
                haptic('selection')
            }
            if (changed || pressStarted) {
                onSelect?.(point)
            }
        },
        [points, onSelect]
    )

    const emitRelease = useCallback((): void => onSelect?.(null), [onSelect])

    // A tap selects on the JS thread first, so the reaction below sees no change and does not report the point twice.
    const selectByTap = useCallback(
        (index: number): void => {
            emitSelection(index, true)
            state.matchedIndex.value = index
            emitRelease()
        },
        [emitSelection, emitRelease, state]
    )

    useAnimatedReaction(
        () => ({ index: selected.value, active: state.isActive.value }),
        (current, previous) => {
            if (previous === null) {
                return
            }
            const started = current.active && !previous.active
            if (current.index !== previous.index || started) {
                scheduleOnRN(emitSelection, current.index, started)
            } else if (previous.active && !current.active) {
                scheduleOnRN(emitRelease)
            }
        },
        [emitSelection, emitRelease]
    )

    return { pressState: state, selected, selectedIndex, selectByTap }
}
