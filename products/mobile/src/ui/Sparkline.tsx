import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import type { Accent, Metric } from '@/model/types'

import { SPARKLINE_HEIGHT, sparklineBarHeight } from './sparklineMath'
import { colors, fonts, lineHeight, sparklineHotColor, type } from './tokens'

interface SparklineProps {
    metric: Metric
    accent: Accent
}

export function Sparkline({ metric, accent }: SparklineProps): ReactElement {
    const hotColor = sparklineHotColor[accent]
    return (
        <View>
            <View style={styles.header}>
                <Text style={[type.eyebrow, styles.label]}>{metric.label}</Text>
                <Text style={styles.range}>{metric.range}</Text>
            </View>
            <View
                style={styles.chart}
                accessibilityRole="image"
                accessibilityLabel={`${metric.label}, ${metric.range}`}
            >
                {metric.bars.map((bar, index) => (
                    <View
                        // biome-ignore lint/suspicious/noArrayIndexKey: bars are positional and never reorder
                        key={index}
                        style={[
                            styles.bar,
                            {
                                height: sparklineBarHeight(bar.value, metric.max),
                                backgroundColor: bar.hot ? hotColor : colors.border,
                            },
                        ]}
                    />
                ))}
            </View>
        </View>
    )
}

const styles = StyleSheet.create({
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
    },
    label: {
        color: colors.tertiary,
    },
    range: {
        fontFamily: fonts.mono,
        fontSize: 11,
        lineHeight: lineHeight(11),
        color: colors.tertiary,
    },
    chart: {
        marginTop: 10,
        flexDirection: 'row',
        alignItems: 'flex-end',
        gap: 3,
        height: SPARKLINE_HEIGHT + 2,
        paddingBottom: 1,
        borderBottomWidth: 1,
        borderBottomColor: colors.border,
    },
    bar: {
        flex: 1,
    },
})
