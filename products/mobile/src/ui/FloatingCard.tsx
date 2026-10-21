import type { ReactElement, ReactNode } from 'react'
import { type StyleProp, View, type ViewStyle } from 'react-native'
import Animated, { useAnimatedStyle } from 'react-native-reanimated'

import { OverlayPortal } from './OverlayPortal'
import { Scrim } from './Scrim'
import { createStyles, useTheme } from './theme'
import { motion, radii } from './tokens'
import { usePresence } from './usePresence'

interface FloatingCardProps {
    visible: boolean
    onClose: () => void
    children: ReactNode
    style?: StyleProp<ViewStyle>
    transformOrigin?: string
    accessory?: ReactNode
    accessibilityLabel?: string
    testID?: string
}

export function FloatingCard({
    visible,
    onClose,
    children,
    style,
    transformOrigin = 'top',
    accessory,
    accessibilityLabel,
    testID,
}: FloatingCardProps): ReactElement | null {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const { mounted, progress } = usePresence(visible, motion.menu, 'emphasized')
    const cardStyle = useAnimatedStyle(() => ({
        opacity: progress.value,
        transform: [{ scale: 0.92 + 0.08 * progress.value }, { translateY: -6 * (1 - progress.value) }],
    }))
    if (!mounted) {
        return null
    }
    return (
        <OverlayPortal>
            <View style={styles.overlay} testID={testID}>
                <Scrim color={colors.scrimLight} progress={progress} onPress={onClose} />
                <Animated.View
                    accessibilityViewIsModal
                    accessibilityLabel={accessibilityLabel}
                    style={[styles.card, shadows.floatingSheet, { transformOrigin }, style, cardStyle]}
                >
                    {children}
                </Animated.View>
                {accessory}
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
    },
    card: {
        position: 'absolute',
        backgroundColor: colors.surface,
        borderRadius: radii.floating,
    },
}))
