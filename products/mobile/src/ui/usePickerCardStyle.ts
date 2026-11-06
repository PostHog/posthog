import type { ComponentProps } from 'react'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import type Animated from 'react-native-reanimated'
import { useAnimatedStyle } from 'react-native-reanimated'
import { useOverlayFrame } from './useOverlayFrame'
import { useOverlayPane } from './useOverlayPane'
import { useScreenInsets } from './useScreenInsets'

export function usePickerCardStyle(top: number, height: number): ComponentProps<typeof Animated.View>['style'] {
    const keyboard = useReanimatedKeyboardAnimation()
    const insets = useScreenInsets()
    const pane = useOverlayPane()
    const frame = useOverlayFrame()
    return useAnimatedStyle(() => {
        const keyboardHeight = Math.max(-keyboard.height.value, 0)
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
    })
}
