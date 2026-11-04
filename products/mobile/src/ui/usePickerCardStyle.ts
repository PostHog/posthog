import type { ComponentProps } from 'react'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import type Animated from 'react-native-reanimated'
import { useAnimatedStyle } from 'react-native-reanimated'

import { useSceneDimensions } from './useSceneDimensions'
import { useScreenInsets } from './useScreenInsets'

export function usePickerCardStyle(top: number, height: number): ComponentProps<typeof Animated.View>['style'] {
    const keyboard = useReanimatedKeyboardAnimation()
    const insets = useScreenInsets()
    const { height: sceneHeight } = useSceneDimensions()
    return useAnimatedStyle(() => {
        const keyboardHeight = Math.max(-keyboard.height.value, 0)
        const bottom = sceneHeight - Math.max(keyboardHeight, insets.bottom) - 4
        const fittedTop = Math.min(top, Math.max(insets.top + 4, bottom - height))
        return { top: fittedTop, height: Math.max(0, Math.min(height, bottom - fittedTop)) }
    })
}
