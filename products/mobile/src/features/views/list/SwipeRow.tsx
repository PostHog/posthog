import { type ReactElement, type ReactNode, useRef } from 'react'
import { type StyleProp, StyleSheet, Text, type ViewStyle } from 'react-native'
import ReanimatedSwipeable, { type SwipeableMethods } from 'react-native-gesture-handler/ReanimatedSwipeable'

import { haptic } from '@/lib/haptics'
import { PinIcon } from '@/ui/icons/PinIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, type } from '@/ui/tokens'

const ACTION_WIDTH = 88

// One row stays open at a time across the screen, like the system lists.
let openRow: SwipeableMethods | null = null

interface SwipeRowProps {
    action: 'pin' | 'unpin'
    onAction: () => void
    /** False renders the row without the swipe, for views only the web can pin. */
    enabled?: boolean
    /** Clips the revealed action to the row's corners. */
    style?: StyleProp<ViewStyle>
    testID?: string
    children: ReactNode
}

/** A row that reveals a Pin or Unpin action when swiped left. */
export function SwipeRow({ action, onAction, enabled = true, style, testID, children }: SwipeRowProps): ReactElement {
    const methods = useRef<SwipeableMethods | null>(null)
    const label = action === 'pin' ? 'Pin' : 'Unpin'
    return (
        <ReanimatedSwipeable
            ref={methods}
            enabled={enabled}
            friction={1.6}
            rightThreshold={ACTION_WIDTH / 2}
            overshootRight={false}
            containerStyle={[styles.container, style]}
            onSwipeableWillOpen={() => {
                if (openRow && openRow !== methods.current) {
                    openRow.close()
                }
                openRow = methods.current
                haptic('selection')
            }}
            onSwipeableClose={() => {
                if (openRow === methods.current) {
                    openRow = null
                }
            }}
            renderRightActions={(_progress, _translation, swipeable) => (
                <Pressable44
                    onPress={() => {
                        swipeable.close()
                        onAction()
                    }}
                    accessibilityLabel={label}
                    hitSlop={0}
                    style={[styles.action, action === 'pin' ? styles.pin : styles.unpin]}
                    testID={testID ? `${testID}-swipe-${action}` : undefined}
                >
                    <PinIcon size={18} color={colors.white} filled={action === 'unpin'} />
                    <Text style={styles.actionText}>{label}</Text>
                </Pressable44>
            )}
        >
            {children}
        </ReanimatedSwipeable>
    )
}

const styles = StyleSheet.create({
    container: {
        overflow: 'hidden',
    },
    action: {
        width: ACTION_WIDTH,
        alignItems: 'center',
        justifyContent: 'center',
        gap: 2,
    },
    pin: {
        backgroundColor: colors.blue,
    },
    unpin: {
        backgroundColor: colors.diffRed,
    },
    actionText: {
        ...type.buttonSmall,
        color: colors.white,
    },
})
