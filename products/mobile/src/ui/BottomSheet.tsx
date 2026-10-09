import { type ReactElement, type ReactNode, useEffect, useState } from 'react'
import { type LayoutChangeEvent, StyleSheet, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated'

import { Scrim } from './Scrim'
import { colors, motion, radii, shadows } from './tokens'
import { usePresence } from './usePresence'
import { bottomOffset, useScreenInsets } from './useScreenInsets'

const DISMISS_DISTANCE = 80
const DISMISS_VELOCITY = 800

interface BottomSheetProps {
    visible: boolean
    onClose: () => void
    children: ReactNode
    paddingHorizontal?: number
    accessibilityLabel?: string
    testID?: string
}

export function BottomSheet({
    visible,
    onClose,
    children,
    paddingHorizontal = 16,
    accessibilityLabel,
    testID,
}: BottomSheetProps): ReactElement | null {
    const insets = useScreenInsets()
    const { mounted, progress } = usePresence(visible, motion.sheet)
    const [height, setHeight] = useState(480)
    const drag = useSharedValue(0)

    useEffect(() => {
        if (visible) {
            drag.value = 0
        }
    }, [visible, drag])

    const pan = Gesture.Pan()
        .runOnJS(true)
        .activeOffsetY(8)
        .onUpdate((event) => {
            drag.value = Math.max(0, event.translationY)
        })
        .onEnd((event) => {
            if (event.translationY > DISMISS_DISTANCE || event.velocityY > DISMISS_VELOCITY) {
                onClose()
            } else {
                drag.value = withTiming(0, { duration: motion.sheet })
            }
        })

    const sheetStyle = useAnimatedStyle(() => ({
        transform: [{ translateY: (1 - progress.value) * height + drag.value }],
    }))

    if (!mounted) {
        return null
    }

    const onLayout = (event: LayoutChangeEvent): void => setHeight(event.nativeEvent.layout.height)

    return (
        <View style={styles.overlay} testID={testID}>
            <Scrim color={colors.scrimDark} progress={progress} onPress={onClose} />
            <GestureDetector gesture={pan}>
                <Animated.View
                    accessibilityViewIsModal
                    accessibilityLabel={accessibilityLabel}
                    onLayout={onLayout}
                    style={[
                        styles.sheet,
                        shadows.bottomSheet,
                        { paddingHorizontal, paddingBottom: bottomOffset(insets, 40) },
                        sheetStyle,
                    ]}
                >
                    <View style={styles.grabber} />
                    {children}
                </Animated.View>
            </GestureDetector>
        </View>
    )
}

const styles = StyleSheet.create({
    overlay: {
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        zIndex: 30,
        justifyContent: 'flex-end',
    },
    sheet: {
        backgroundColor: colors.white,
        borderTopLeftRadius: radii.sheet,
        borderTopRightRadius: radii.sheet,
        paddingTop: 10,
    },
    grabber: {
        width: 40,
        height: 5,
        borderRadius: 3,
        backgroundColor: colors.border,
        alignSelf: 'center',
    },
})
