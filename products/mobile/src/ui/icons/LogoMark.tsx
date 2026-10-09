import type { ReactElement } from 'react'
import { StyleSheet, View } from 'react-native'

import { colors } from '../tokens'

const VARIANTS = {
    small: { width: 4, heights: [10, 14, 18], gap: 2, radius: 1 },
    large: { width: 6, heights: [16, 22, 28], gap: 3, radius: 1.5 },
} as const

const BAR_COLORS = [colors.orange, colors.yellow, colors.blue] as const

interface LogoMarkProps {
    variant?: keyof typeof VARIANTS
}

export function LogoMark({ variant = 'small' }: LogoMarkProps): ReactElement {
    const v = VARIANTS[variant]
    return (
        <View
            style={[styles.row, { gap: v.gap, height: v.heights[2] }]}
            accessibilityRole="image"
            accessibilityLabel="PostHog"
        >
            {BAR_COLORS.map((color, i) => (
                <View
                    key={color}
                    style={{ width: v.width, height: v.heights[i], backgroundColor: color, borderRadius: v.radius }}
                />
            ))}
        </View>
    )
}

const styles = StyleSheet.create({
    row: {
        flexDirection: 'row',
        alignItems: 'flex-end',
    },
})
