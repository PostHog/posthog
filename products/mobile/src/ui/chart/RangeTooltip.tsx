import type { ReactElement } from 'react'
import { type LayoutChangeEvent, StyleSheet, Text, View } from 'react-native'

import { colors, lineHeight, shadows, space } from '@/ui/tokens'

import type { RangeContent } from './chartSeries'

export const CHART_RANGE_TOOLTIP_TEST_ID = 'chart-range-tooltip'

interface RangeTooltipProps {
    content: RangeContent
    left: number
    top: number
    maxWidth: number
    onLayout: (event: LayoutChangeEvent) => void
    testID?: string
}

/** The two-finger result: "Oct 1 → Oct 14", then each series' two values and the change between them. */
export function RangeTooltip({ content, left, top, maxWidth, onLayout, testID }: RangeTooltipProps): ReactElement {
    return (
        <View onLayout={onLayout} style={[styles.card, { left, top, maxWidth }]} testID={testID}>
            <Text style={styles.header} numberOfLines={1}>
                {content.header}
            </Text>
            {content.rows.map((row) => (
                <View key={row.key}>
                    <View style={styles.row}>
                        <View style={[styles.swatch, { backgroundColor: row.color }]} />
                        <Text style={styles.label} numberOfLines={1}>
                            {row.label}
                        </Text>
                    </View>
                    <Text style={styles.detail}>{row.values}</Text>
                    <Text style={styles.detail}>{row.change}</Text>
                </View>
            ))}
        </View>
    )
}

const styles = StyleSheet.create({
    card: {
        position: 'absolute',
        pointerEvents: 'none',
        minWidth: 112,
        paddingHorizontal: space[10],
        paddingTop: 7,
        paddingBottom: space[8],
        borderRadius: 10,
        backgroundColor: colors.ink,
        ...shadows.popover,
    },
    header: {
        fontSize: 12,
        lineHeight: lineHeight(12, 1.35),
        color: colors.disabled,
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
        fontSize: 12,
        lineHeight: lineHeight(12, 1.35),
        color: colors.border,
    },
    detail: {
        fontSize: 12,
        lineHeight: lineHeight(12, 1.35),
        fontVariant: ['tabular-nums'],
        color: colors.white,
    },
})
