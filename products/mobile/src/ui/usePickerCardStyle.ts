import type { ComponentProps } from 'react'
import { useKeyboardState, useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import type Animated from 'react-native-reanimated'
import { useAnimatedStyle } from 'react-native-reanimated'
import type { DisplayRect } from './displayRegions'
import { useOverlayFrame } from './useOverlayFrame'
import { useOverlayPane } from './useOverlayPane'
import { type ScreenInsets, useScreenInsets } from './useScreenInsets'

interface PickerCardFrame {
    left: number
    right: number
    top: number
    height: number
}

function fitPickerCard(
    top: number,
    height: number,
    keyboardHeight: number,
    insets: ScreenInsets,
    pane: DisplayRect,
    frame: DisplayRect
): PickerCardFrame {
    'worklet'
    const bottom = Math.min(pane.y + pane.height - insets.bottom, frame.height - keyboardHeight) - 4
    const minimumTop = pane.y + (pane.y === 0 ? insets.top : 0) + 4
    const fittedTop = Math.min(Math.max(top, minimumTop), Math.max(minimumTop, bottom - height))
    const side = Math.max(14, (pane.width - 600) / 2)
    return {
        left: pane.x + side,
        right: frame.width - pane.x - pane.width + side,
        top: fittedTop,
        height: Math.max(0, Math.min(height, bottom - fittedTop)),
    }
}

export function usePickerCardStyle(top: number, height: number): ComponentProps<typeof Animated.View>['style'] {
    const keyboard = useReanimatedKeyboardAnimation()
    const insets = useScreenInsets()
    const pane = useOverlayPane()
    const frame = useOverlayFrame()
    return useAnimatedStyle(() => fitPickerCard(top, height, Math.max(-keyboard.height.value, 0), insets, pane, frame))
}

/** The height `usePickerCardStyle` settles at once the keyboard stops moving, for layout choices made in React. */
export function usePickerCardHeight(top: number, height: number): number {
    const keyboardHeight = useKeyboardState((state) => (state.isVisible ? state.height : 0))
    const insets = useScreenInsets()
    const pane = useOverlayPane()
    const frame = useOverlayFrame()
    return fitPickerCard(top, height, keyboardHeight, insets, pane, frame).height
}
