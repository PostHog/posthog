import type { ReactElement } from 'react'
import { type LayoutChangeEvent, StyleSheet, Text, View } from 'react-native'

import { colors, fonts, lineHeight, shadows, space } from '@/ui/tokens'

interface ChartTooltipProps {
    title: string
    label: string
    value: string
    color: string
    left: number
    top: number
    onLayout: (event: LayoutChangeEvent) => void
    testID?: string
}

export function ChartTooltip({
    title,
    label,
    value,
    color,
    left,
    top,
    onLayout,
    testID,
}: ChartTooltipProps): ReactElement {
    return (
        <View onLayout={onLayout} style={[styles.card, { left, top }]} testID={testID}>
            <Text style={styles.title} numberOfLines={1}>
                {title}
            </Text>
            <View style={styles.row}>
                <View style={[styles.swatch, { backgroundColor: color }]} />
                <Text style={styles.label} numberOfLines={1}>
                    {label}
                </Text>
                <Text style={styles.value} numberOfLines={1}>
                    {value}
                </Text>
            </View>
        </View>
    )
}

const styles = StyleSheet.create({
    card: {
        position: 'absolute',
        pointerEvents: 'none',
        maxWidth: 240,
        paddingHorizontal: space[10],
        paddingVertical: space[8],
        gap: space[4],
        borderRadius: 8,
        borderWidth: StyleSheet.hairlineWidth,
        borderColor: colors.border,
        backgroundColor: colors.white,
        ...shadows.popover,
    },
    title: {
        fontSize: 12,
        lineHeight: lineHeight(12),
        fontWeight: '600',
        color: colors.secondary,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: space[6],
    },
    swatch: {
        width: 8,
        height: 8,
        borderRadius: 2,
    },
    label: {
        flexShrink: 1,
        fontSize: 13,
        lineHeight: lineHeight(13),
        color: colors.ink,
    },
    value: {
        marginLeft: space[8],
        fontFamily: fonts.mono,
        fontSize: 12,
        lineHeight: lineHeight(12),
        fontWeight: '600',
        color: colors.ink,
    },
})
