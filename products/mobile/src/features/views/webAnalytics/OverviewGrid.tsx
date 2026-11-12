import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { formatMetricValue } from '@/model/adapters/metric'
import { isWebTrendMetric } from '@/model/adapters/webAnalytics'
import type { NumberDelta, WebOverviewMetric, WebTrendMetric } from '@/model/views'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { DeltaPill } from '../DeltaPill'

interface OverviewGridProps {
    metrics: readonly WebOverviewMetric[]
    selected: WebTrendMetric
    onSelect: (metric: WebTrendMetric) => void
    stale: boolean
}

function rows(metrics: readonly WebOverviewMetric[]): WebOverviewMetric[][] {
    const result: WebOverviewMetric[][] = []
    for (let index = 0; index < metrics.length; index += 2) {
        result.push(metrics.slice(index, index + 2))
    }
    return result
}

function changeDelta(metric: WebOverviewMetric): NumberDelta | null {
    if (metric.value === null || metric.previous === null || metric.changePercent === null) {
        return null
    }
    return {
        previous: metric.previous,
        change: metric.value - metric.previous,
        percent: metric.changePercent,
        unit: 'percent',
        basis: 'compare',
        previousAt: null,
    }
}

/** On a phone the cards are the trend's series switcher. Revenue and conversion numbers have no trend. */
export function OverviewGrid({ metrics, selected, onSelect, stale }: OverviewGridProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={[styles.grid, stale && styles.dimmed]} accessibilityRole="radiogroup">
            {rows(metrics).map((row) => (
                <View key={row[0]?.key} style={styles.row}>
                    {row.map((metric) => (
                        <MetricCard
                            key={metric.key}
                            metric={metric}
                            wide={row.length === 1}
                            selected={metric.key === selected}
                            onSelect={onSelect}
                        />
                    ))}
                </View>
            ))}
        </View>
    )
}

interface MetricCardProps {
    metric: WebOverviewMetric
    wide: boolean
    selected: boolean
    onSelect: (metric: WebTrendMetric) => void
}

function MetricCard({ metric, wide, selected, onSelect }: MetricCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const formatValue = (value: number): string =>
        formatMetricValue(value, metric.format.valueFormat, metric.format.unit)
    const delta = changeDelta(metric)
    const value = metric.value === null ? '–' : formatValue(metric.value)
    const prior = metric.previous === null ? null : `vs ${formatValue(metric.previous)} prior`
    const pill = delta ? <DeltaPill delta={delta} formatValue={formatValue} basis="vs previous period" /> : null
    const body = wide ? (
        <View style={styles.wideBody}>
            <View style={styles.wideText}>
                <Text style={styles.label} numberOfLines={1}>
                    {metric.label}
                </Text>
                {prior ? <Text style={styles.prior}>{prior}</Text> : null}
            </View>
            <View style={styles.wideValue}>
                <Text style={styles.value} numberOfLines={1} adjustsFontSizeToFit>
                    {value}
                </Text>
                {pill}
            </View>
        </View>
    ) : (
        <>
            <Text style={styles.label} numberOfLines={1}>
                {metric.label}
            </Text>
            <Text style={styles.value} numberOfLines={1} adjustsFontSizeToFit>
                {value}
            </Text>
            {pill}
            {prior ? (
                <Text style={styles.prior} numberOfLines={1}>
                    {prior}
                </Text>
            ) : null}
        </>
    )
    const key = metric.key
    const testID = `web-metric-${key.replace(/\s+/g, '-')}`
    if (!isWebTrendMetric(key)) {
        return (
            <View style={[styles.card, wide && styles.cardWide]} testID={testID}>
                {body}
            </View>
        )
    }
    return (
        <Pressable44
            onPress={() => onSelect(key)}
            hitSlop={0}
            accessibilityRole="radio"
            accessibilityState={{ selected }}
            accessibilityLabel={`${metric.label}, ${value}${prior ? `, ${prior}` : ''}`}
            accessibilityHint="Shows this metric in the chart below."
            pressedBackground={colors.sunken}
            style={[styles.card, wide && styles.cardWide, selected && styles.cardSelected]}
            testID={testID}
        >
            {body}
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    grid: {
        gap: 10,
    },
    row: {
        flexDirection: 'row',
        gap: 10,
    },
    dimmed: {
        opacity: 0.5,
    },
    card: {
        flex: 1,
        minWidth: 0,
        gap: 6,
        padding: 12,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        alignItems: 'flex-start',
    },
    cardWide: {
        alignItems: 'stretch',
    },
    // The border grows inward by the padding it takes away, so a selected card keeps its size.
    cardSelected: {
        borderWidth: 2,
        borderColor: colors.ink,
        padding: 11,
    },
    wideBody: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    wideText: {
        flex: 1,
        minWidth: 0,
        gap: 6,
    },
    wideValue: {
        alignItems: 'flex-end',
        gap: 6,
    },
    label: {
        ...type.meta,
        color: colors.muted,
    },
    value: {
        fontSize: 24,
        lineHeight: 29,
        fontWeight: '700',
        letterSpacing: -0.4,
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    prior: {
        ...type.meta,
        color: colors.tertiary,
        fontVariant: ['tabular-nums'],
    },
}))
