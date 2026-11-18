import { GlassView } from 'expo-glass-effect'
import { type ComponentProps, type ReactElement, type ReactNode, useState } from 'react'
import { View } from 'react-native'
import Animated, { useAnimatedStyle, useReducedMotion } from 'react-native-reanimated'

import { OverlayPortal } from './OverlayPortal'
import { Scrim } from './Scrim'
import { boxShadow, createStyles, GlassSurfaceContext, useTheme } from './theme'
import { motion, radii } from './tokens'
import { useOverlayBack } from './useOverlayBack'
import { usePresence } from './usePresence'

interface FloatingCardProps {
    visible: boolean
    onClose: () => void
    children: ReactNode
    style?: ComponentProps<typeof Animated.View>['style']
    transformOrigin?: string
    accessory?: ReactNode
    accessibilityLabel?: string
    testID?: string
    /**
     * Draws the card as Liquid Glass. Pass `useLiquidGlass()`, which is false wherever the card must stay solid, and
     * style the card's own content with the same value (`useStyles(glass)`).
     */
    glass?: boolean
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
    glass = false,
}: FloatingCardProps): ReactElement | null {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const { mounted, progress } = usePresence(visible, motion.menu, 'emphasized')
    useOverlayBack(visible, onClose)
    const fadeStyle = useAnimatedStyle(() => ({ opacity: progress.value }))
    const motionStyle = useAnimatedStyle(() => ({
        transform: [{ scale: 0.92 + 0.08 * progress.value }, { translateY: -6 * (1 - progress.value) }],
    }))
    if (!mounted) {
        return null
    }
    return (
        <OverlayPortal>
            <View style={styles.overlay} testID={testID}>
                <Scrim color={glass ? colors.scrimGlass : colors.scrimLight} progress={progress} onPress={onClose} />
                {glass ? (
                    // UIKit drops the glass effect under a view with an opacity below 1, so the card only scales and
                    // its content fades over a glass that materializes on its own.
                    <Animated.View
                        accessibilityViewIsModal
                        accessibilityLabel={accessibilityLabel}
                        style={[styles.card, { transformOrigin }, style, styles.glassCard, motionStyle]}
                    >
                        <CardGlass visible={visible} />
                        <Animated.View style={[styles.glassContent, fadeStyle]}>
                            <GlassSurfaceContext.Provider value>{children}</GlassSurfaceContext.Provider>
                        </Animated.View>
                    </Animated.View>
                ) : (
                    <Animated.View
                        accessibilityViewIsModal
                        accessibilityLabel={accessibilityLabel}
                        style={[styles.card, shadows.floatingSheet, { transformOrigin }, style, fadeStyle, motionStyle]}
                    >
                        {children}
                    </Animated.View>
                )}
                {accessory}
            </View>
        </OverlayPortal>
    )
}

function CardGlass({ visible }: { visible: boolean }): ReactElement {
    const styles = useStyles()
    const { scheme } = useTheme()
    const reduceMotion = useReducedMotion()
    // UIKit animates a change of glass style, not a glass that is there from the first frame. The glass starts empty
    // and turns on after its first layout, so it materializes as the card opens.
    const [laidOut, setLaidOut] = useState(false)
    return (
        <GlassView
            onLayout={() => setLaidOut(true)}
            glassEffectStyle={{
                style: visible && laidOut ? 'regular' : 'none',
                animate: !reduceMotion,
                animationDuration: motion.menu / 1000,
            }}
            // Follows the app's Appearance setting, which can differ from the system's.
            colorScheme={scheme}
            style={styles.glass}
            testID="floating-card-glass"
        />
    )
}

const useStyles = createStyles(({ colors, scheme }) => ({
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
    // After the caller's style: the glass draws the card's fill and edge.
    glassCard: {
        backgroundColor: 'transparent',
        borderWidth: 0,
        boxShadow: boxShadow('floatingSheet', scheme),
    },
    glass: {
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        borderRadius: radii.floating,
    },
    glassContent: {
        flexShrink: 1,
    },
}))
