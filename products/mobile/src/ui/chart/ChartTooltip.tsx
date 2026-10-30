import type { ReactElement } from 'react'
import { type LayoutChangeEvent, Pressable, Text, View } from 'react-native'

import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { createStyles, useColors } from '@/ui/theme'
import { lineHeight, space } from '@/ui/tokens'

import type { TooltipContent } from './chartSeries'

export const TOOLTIP_MAX_WIDTH = 204

/**
 * The same id on every chart. A screen pins one chart at a time, so the id finds the open tooltip without naming
 * its chart.
 */
export const CHART_TOOLTIP_TEST_ID = 'chart-tooltip'

interface ChartTooltipProps {
    content: TooltipContent
    formatValue: (value: number) => string
    left: number
    top: number
    maxWidth: number
    /** A tap opens the Point sheet. Without it the tooltip lets touches through to the chart. */
    onPress?: () => void
    onLayout: (event: LayoutChangeEvent) => void
    testID?: string
}

/** The pinned point: bucket header, one row per series, the previous period, the in-progress note and a chevron. */
export function ChartTooltip({
    content,
    formatValue,
    left,
    top,
    maxWidth,
    onPress,
    onLayout,
    testID,
}: ChartTooltipProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const body = (
        <>
            <Text style={styles.header} numberOfLines={1}>
                {content.header}
            </Text>
            {content.rows.map((row) => (
                <View key={row.key} style={styles.row}>
                    <View style={[styles.swatch, { backgroundColor: row.color }]} />
                    <Text style={styles.label} numberOfLines={1}>
                        {row.label}
                    </Text>
                    <Text style={styles.value} numberOfLines={1}>
                        {formatValue(row.value)}
                    </Text>
                </View>
            ))}
            {content.more > 0 ? <Text style={styles.detail}>+{content.more} more</Text> : null}
            {content.compare ? (
                <>
                    <Text style={styles.detail}>{content.compare.previous}</Text>
                    <Text style={styles.detail}>{content.compare.change}</Text>
                </>
            ) : null}
            {content.note ? <Text style={styles.note}>{content.note}</Text> : null}
        </>
    )
    const position = { left, top, maxWidth }
    if (!onPress) {
        return (
            <View onLayout={onLayout} style={[styles.card, styles.passive, position]} testID={testID}>
                {body}
            </View>
        )
    }
    return (
        <Pressable
            onLayout={onLayout}
            onPress={onPress}
            style={({ pressed }) => [styles.card, styles.withChevron, position, pressed ? styles.pressed : null]}
            accessibilityRole="button"
            accessibilityLabel={`Show details for ${content.header}`}
            testID={testID}
        >
            {body}
            <View style={styles.chevron} pointerEvents="none">
                <ChevronRightIcon size={12} color={colors.disabled} strokeWidth={2.2} />
            </View>
        </Pressable>
    )
}

// An ink card in both schemes, so it stands out from the chart.
const useStyles = createStyles(({ colors, shadows }) => ({
    card: {
        position: 'absolute',
        minWidth: 112,
        paddingLeft: space[10],
        paddingRight: space[10],
        paddingTop: 7,
        paddingBottom: space[8],
        borderRadius: 10,
        backgroundColor: colors.ink,
        ...shadows.popover,
    },
    passive: {
        pointerEvents: 'none',
    },
    withChevron: {
        paddingRight: 26,
    },
    pressed: {
        backgroundColor: colors.inkHover,
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
    value: {
        flexShrink: 0,
        marginLeft: 'auto',
        paddingLeft: space[8],
        fontSize: 14,
        lineHeight: lineHeight(14, 1.35),
        fontWeight: '700',
        fontVariant: ['tabular-nums'],
        color: colors.onInk,
    },
    detail: {
        fontSize: 12,
        lineHeight: lineHeight(12, 1.35),
        fontVariant: ['tabular-nums'],
        color: colors.border,
    },
    note: {
        marginTop: 3,
        fontSize: 12,
        lineHeight: lineHeight(12, 1.35),
        color: colors.disabled,
    },
    chevron: {
        position: 'absolute',
        right: 7,
        top: 0,
        bottom: 0,
        justifyContent: 'center',
    },
}))
