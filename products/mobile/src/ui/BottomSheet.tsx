import { type ReactElement, type ReactNode, useState } from 'react'
import { type LayoutChangeEvent, View } from 'react-native'
import { GestureDetector } from 'react-native-gesture-handler'
import Animated, { type SharedValue, useAnimatedStyle } from 'react-native-reanimated'
import type { NativeGesture } from '@/ui/gestureTypes'

import { OverlayPortal } from './OverlayPortal'
import { Scrim } from './Scrim'
import { createStyles, useTheme } from './theme'
import { layout, motion, radii } from './tokens'
import { useOverlayBack } from './useOverlayBack'
import { useOverlayFrame } from './useOverlayFrame'
import { useOverlayPane } from './useOverlayPane'
import { usePresence } from './usePresence'
import { bottomOffset, useScreenInsets } from './useScreenInsets'
import { useSheetDrag } from './useSheetDrag'

interface BottomSheetProps {
    visible: boolean
    onClose: () => void
    children: ReactNode
    paddingHorizontal?: number
    scrollGesture?: NativeGesture
    keyboardHeight?: SharedValue<number>
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
    keyboardHeight,
    backgroundColor,
    accessibilityLabel,
    testID,
}: BottomSheetProps): ReactElement | null {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const insets = useScreenInsets()
    const pane = useOverlayPane()
    const frame = useOverlayFrame()
    const sceneHeight = pane.height
    const width = pane.width
    const topInset = pane.y === 0 ? insets.top : 0
    const bottomMargin = width >= 600 ? insets.bottom + 16 : 0
    const bottomPadding = bottomOffset(insets, 40)
    const { mounted, progress } = usePresence(visible, motion.sheet)
    const [height, setHeight] = useState(480)
    const { drag, pan } = useSheetDrag(visible, onClose, scrollGesture)
    useOverlayBack(visible, onClose)

    const sheetStyle = useAnimatedStyle(() => {
        const keyboard = Math.max(pane.y + pane.height - frame.height - (keyboardHeight?.value ?? 0), 0)
        const compactKeyboard = keyboard > 0 && sceneHeight < 480
        const marginBottom = keyboard > 0 ? Math.max(bottomMargin, keyboard + (compactKeyboard ? 4 : 8)) : bottomMargin
        return {
            transform: [{ translateY: (1 - progress.value) * height + drag.value }],
            marginBottom,
            maxHeight: Math.max(0, sceneHeight - topInset - (compactKeyboard ? 4 : 12) - marginBottom),
            paddingBottom: compactKeyboard ? 8 : keyboard > 0 ? layout.minBottomPadding : bottomPadding,
        }
    })

    if (!mounted) {
        return null
    }

    const onLayout = (event: LayoutChangeEvent): void => setHeight(event.nativeEvent.layout.height)

    return (
        <OverlayPortal>
            <View style={styles.overlay} testID={testID}>
                <Scrim color={colors.scrimDark} progress={progress} onPress={onClose} />
                <View
                    style={{
                        position: 'absolute',
                        left: pane.x,
                        top: pane.y,
                        width: pane.width,
                        height: pane.height,
                        justifyContent: 'flex-end',
                    }}
                    pointerEvents="box-none"
                >
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
                                    width: '100%',
                                    maxWidth: 600,
                                    alignSelf: 'center',
                                    ...(width >= 600
                                        ? {
                                              borderBottomLeftRadius: radii.sheet,
                                              borderBottomRightRadius: radii.sheet,
                                          }
                                        : {}),
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
