import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { createStyles, type ThemeColors, useColors } from '@/ui/theme'
import { type } from '@/ui/tokens'

import { axisPosition, type ChangeUnit, formatDelta, type IntervalSide } from './detailModel'

interface IntervalBarProps {
    interval: [number, number]
    delta: number
    unit: ChangeUnit
    /** Half the axis width, shared by every bar on one card. */
    scale: number
    side: IntervalSide
    /** `large` labels 0 and both ends, for the About sheet. */
    size?: 'small' | 'large'
}

function bandColor(side: IntervalSide, colors: ThemeColors): string {
    return side === 'good' ? colors.diffGreen : side === 'bad' ? colors.diffRed : colors.disabled
}

function percent(position: number): `${number}%` {
    return `${Math.round(position * 1000) / 10}%`
}

/**
 * The interval of a variant's change as a band against 0. Green when the whole range is on the good side of 0, red on
 * the bad side, gray when it crosses 0. Plain views, so it costs nothing to draw in a list of cells.
 */
export function IntervalBar({ interval, delta, unit, scale, side, size = 'small' }: IntervalBarProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const low = axisPosition(interval[0], scale)
    const high = axisPosition(interval[1], scale)
    const zero = axisPosition(0, scale)
    const mark = axisPosition(delta, scale)
    const large = size === 'large'
    const band = (
        <View style={large ? styles.trackLarge : styles.track}>
            <View style={[styles.line, large && styles.lineLarge]} />
            <View
                style={[
                    large ? styles.bandLarge : styles.band,
                    {
                        left: percent(low),
                        width: percent(Math.max(0.01, high - low)),
                        backgroundColor: bandColor(side, colors),
                    },
                ]}
            />
            <View style={[large ? styles.zeroLarge : styles.zero, { left: percent(zero) }]} />
            <View style={[large ? styles.markLarge : styles.mark, { left: percent(mark) }]} />
        </View>
    )
    if (!large) {
        return (
            <View importantForAccessibility="no-hide-descendants" accessibilityElementsHidden>
                {band}
            </View>
        )
    }
    return (
        <View
            accessible
            accessibilityLabel={`Range from ${formatDelta(interval[0], unit)} to ${formatDelta(interval[1], unit)}, best estimate ${formatDelta(delta, unit)}`}
            style={styles.large}
        >
            <View style={styles.labelRow}>
                <Text style={[styles.zeroLabel, { left: percent(zero) }]}>0</Text>
            </View>
            {band}
            <View style={styles.labelRow}>
                <Text style={[styles.endLabel, { left: percent(low) }]} numberOfLines={1}>
                    {formatDelta(interval[0], unit)}
                </Text>
                <Text style={[styles.endLabel, { left: percent(high) }]} numberOfLines={1}>
                    {formatDelta(interval[1], unit)}
                </Text>
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    track: {
        height: 12,
        justifyContent: 'center',
    },
    line: {
        position: 'absolute',
        left: 0,
        right: 0,
        height: 1,
        backgroundColor: colors.border,
    },
    band: {
        position: 'absolute',
        height: 6,
        borderRadius: 3,
    },
    zero: {
        position: 'absolute',
        width: 1.5,
        height: 12,
        marginLeft: -0.75,
        backgroundColor: colors.tertiary,
    },
    mark: {
        position: 'absolute',
        width: 2,
        height: 12,
        marginLeft: -1,
        borderRadius: 1,
        backgroundColor: colors.ink,
    },
    large: {
        paddingHorizontal: 28,
        gap: 6,
    },
    trackLarge: {
        height: 24,
        justifyContent: 'center',
    },
    lineLarge: {
        height: 1.5,
    },
    bandLarge: {
        position: 'absolute',
        height: 14,
        borderRadius: 7,
    },
    zeroLarge: {
        position: 'absolute',
        width: 2,
        height: 24,
        marginLeft: -1,
        backgroundColor: colors.tertiary,
    },
    markLarge: {
        position: 'absolute',
        width: 3,
        height: 24,
        marginLeft: -1.5,
        borderRadius: 1.5,
        backgroundColor: colors.ink,
    },
    labelRow: {
        height: 18,
    },
    zeroLabel: {
        ...type.monoSmall,
        position: 'absolute',
        width: 40,
        marginLeft: -20,
        textAlign: 'center',
        color: colors.tertiary,
    },
    endLabel: {
        ...type.meta,
        fontWeight: '600',
        position: 'absolute',
        width: 72,
        marginLeft: -36,
        textAlign: 'center',
        color: colors.muted,
    },
}))
