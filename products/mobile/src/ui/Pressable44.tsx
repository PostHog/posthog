import type { ReactElement, Ref } from 'react'
import {
    type GestureResponderEvent,
    Pressable,
    type PressableProps,
    type PressableStateCallbackType,
    type StyleProp,
    type View,
    type ViewStyle,
} from 'react-native'

import { type HapticKind, haptic } from '@/lib/haptics'

export interface Pressable44Props extends Omit<PressableProps, 'style'> {
    ref?: Ref<View>
    style?: StyleProp<ViewStyle>
    pressedBackground?: string
    pressedStyle?: StyleProp<ViewStyle>
    haptic?: HapticKind
}

/** react-native-web adds `hovered` to the press state. */
type PressState = PressableStateCallbackType & { hovered?: boolean }

// Visual sizes go down to 34pt, so the default hit slop adds 6pt on each side; smaller targets pass a larger `hitSlop`.
export function Pressable44({
    style,
    pressedBackground,
    pressedStyle,
    haptic: hapticKind,
    hitSlop = 6,
    onPress,
    accessibilityRole = 'button',
    ...rest
}: Pressable44Props): ReactElement {
    const handlePress = (event: GestureResponderEvent): void => {
        if (hapticKind) {
            haptic(hapticKind)
        }
        onPress?.(event)
    }
    return (
        <Pressable
            {...rest}
            accessibilityRole={accessibilityRole}
            hitSlop={hitSlop}
            onPress={handlePress}
            style={(state: PressState) => {
                const active = (state.pressed || state.hovered === true) && !rest.disabled
                return [
                    style,
                    active && pressedBackground ? { backgroundColor: pressedBackground } : null,
                    active ? pressedStyle : null,
                ]
            }}
        />
    )
}
