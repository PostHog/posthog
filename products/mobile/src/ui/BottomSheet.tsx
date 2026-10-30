import { type ReactElement, type ReactNode, useState } from 'react'
import { type LayoutChangeEvent, View } from 'react-native'
import { GestureDetector, type NativeGesture } from 'react-native-gesture-handler'
import Animated, { useAnimatedStyle } from 'react-native-reanimated'

import { OverlayPortal } from './OverlayPortal'
import { Scrim } from './Scrim'
import { createStyles, useTheme } from './theme'
import { motion, radii } from './tokens'
import { usePresence } from './usePresence'
import { bottomOffset, useScreenInsets } from './useScreenInsets'
import { useSheetDrag } from './useSheetDrag'

interface BottomSheetProps {
    visible: boolean
    onClose: () => void
    children: ReactNode
    paddingHorizontal?: number
    scrollGesture?: NativeGesture
    /** Defaults to `surface`. Sheets that hold surface cards use the screen background. */
    backgroundColor?: string
    accessibilityLabel?: string
    testID?: string
}

export function BottomSheet({
    visible,
    onClose,
    children,
    paddingHorizontal = 16,
    scrollGesture,
    backgroundColor,
    accessibilityLabel,
    testID,
}: BottomSheetProps): ReactElement | null {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const insets = useScreenInsets()
    const { mounted, progress } = usePresence(visible, motion.sheet)
    const [height, setHeight] = useState(480)
    const { drag, pan } = useSheetDrag(visible, onClose, scrollGesture)

    const sheetStyle = useAnimatedStyle(() => ({
        transform: [{ translateY: (1 - progress.value) * height + drag.value }],
    }))

    if (!mounted) {
        return null
    }

    const onLayout = (event: LayoutChangeEvent): void => setHeight(event.nativeEvent.layout.height)

    return (
        <OverlayPortal>
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
                            {
                                paddingHorizontal,
                                paddingBottom: bottomOffset(insets, 40),
                                backgroundColor: backgroundColor ?? colors.surface,
                            },
                            sheetStyle,
                        ]}
                    >
                        <View style={styles.grabber} />
                        {children}
                    </Animated.View>
                </GestureDetector>
            </View>
        </OverlayPortal>
    )
}

const useStyles = createStyles(({ colors }) => ({
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
}))
