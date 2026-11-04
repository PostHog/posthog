import { type ReactElement, type ReactNode, useCallback } from 'react'
import { Text, View } from 'react-native'
import Animated, { useAnimatedStyle } from 'react-native-reanimated'

import { GripIcon } from '@/ui/icons/GripIcon'
import { createStyles, useTheme } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'
import { useSceneDimensions } from '@/ui/useSceneDimensions'
import type { PinDrag } from './usePinDrag'
import { ViewIcon } from './viewMeta'

export function PinDragTile({ id, drag, children }: { id: string; drag: PinDrag; children: ReactNode }): ReactElement {
    const { register, measure } = drag
    const ref = useCallback((node: View | null) => register(id, node), [id, register])
    return (
        <View
            ref={ref}
            collapsable={false}
            onLayout={() => measure(id)}
            style={{ opacity: drag.dragged?.shortcutId === id ? 0.35 : 1 }}
        >
            {children}
        </View>
    )
}

/** A compact label follows the finger without mounting a second live chart or stealing its canvas budget. */
export function PinDragOverlay({ drag }: { drag: PinDrag }): ReactElement | null {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const { width } = useSceneDimensions()
    const { x, y, targetX, targetY, targetWidth, targetHeight } = drag
    const preview = useAnimatedStyle(() => ({
        transform: [{ translateX: Math.max(8, Math.min(width - 268, x.value - 130)) }, { translateY: y.value - 78 }],
    }))
    const target = useAnimatedStyle(() => ({
        left: targetX.value,
        top: targetY.value,
        width: targetWidth.value,
        height: targetHeight.value,
    }))
    if (!drag.dragged) return null
    return (
        <View
            pointerEvents="none"
            style={styles.overlay}
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            testID="views-pin-drag"
        >
            <Animated.View style={[styles.target, target]} />
            <Animated.View style={[styles.preview, shadows.floatingSheet, preview]}>
                <ViewIcon kind={drag.dragged.kind} size={20} />
                <View style={styles.text}>
                    <Text style={styles.title} numberOfLines={1}>
                        {drag.dragged.name}
                    </Text>
                    <Text style={styles.hint}>Release to place here</Text>
                </View>
                <GripIcon size={20} color={colors.tertiary} />
            </Animated.View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    overlay: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
    target: {
        position: 'absolute',
        borderWidth: 2,
        borderColor: colors.blue,
        borderRadius: radii.option,
        backgroundColor: colors.blueHighlight,
    },
    preview: {
        position: 'absolute',
        left: 0,
        top: 0,
        width: 260,
        padding: 12,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        borderRadius: radii.option,
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.blue,
    },
    text: { flex: 1, minWidth: 0 },
    title: { ...type.bodySmallStrong, color: colors.ink },
    hint: { ...type.meta, color: colors.secondary },
}))
