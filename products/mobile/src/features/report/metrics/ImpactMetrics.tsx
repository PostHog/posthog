import type { ReactElement } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { MISSING_VALUE } from '@/features/metrics/metricValue'
import { useMetricValue } from '@/features/metrics/useMetricValue'
import type { MetricView } from '@/model/types'
import { Eyebrow } from '@/ui/Eyebrow'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { fonts, lineHeight, radii, type } from '@/ui/tokens'

import { insightUrl, openInsight } from './openInsight'

interface ImpactMetricsProps {
    metrics: MetricView[]
    reportId: string
}

function pairs<T>(items: readonly T[]): [T, T | undefined][] {
    const rows: [T, T | undefined][] = []
    for (let index = 0; index < items.length; index += 2) {
        rows.push([items[index] as T, items[index + 1]])
    }
    return rows
}

export function ImpactMetrics({ metrics, reportId }: ImpactMetricsProps): ReactElement | null {
    const styles = useStyles()
    if (metrics.length === 0) {
        return null
    }
    return (
        <View style={styles.section} testID="report-impact">
            <Eyebrow>Impact</Eyebrow>
            <View style={styles.grid}>
                {pairs(metrics).map(([left, right]) => (
                    <View key={left.metricId} style={styles.row}>
                        <View style={styles.tileSlot}>
                            <MetricTile metric={left} reportId={reportId} />
                        </View>
                        {/* Padding and borders sit outside the flex share in Yoga, so each tile fills a plain slot. */}
                        <View style={styles.tileSlot}>
                            {right ? <MetricTile metric={right} reportId={reportId} /> : null}
                        </View>
                    </View>
                ))}
            </View>
        </View>
    )
}

function MetricTile({ metric, reportId }: { metric: MetricView; reportId: string }): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const value = useMetricValue(metric)
    const openUrl = insightUrl(metric.openUrl)
    const footer = value.kind === 'saved' && value.measured ? value.measured : metric.windowLabel
    const failed = (value.kind === 'saved' || value.kind === 'missing') && value.failed
    const body = (
        <>
            {value.kind === 'loading' ? (
                <View style={styles.valueBox}>
                    <ActivityIndicator
                        size="small"
                        color={colors.tertiary}
                        accessibilityLabel="Loading current value"
                    />
                </View>
            ) : (
                <Text
                    style={[styles.value, value.kind === 'missing' && styles.missing]}
                    numberOfLines={1}
                    adjustsFontSizeToFit
                >
                    {value.kind === 'missing' ? MISSING_VALUE : value.text}
                </Text>
            )}
            <Text style={styles.title} numberOfLines={2}>
                {metric.title}
            </Text>
            <Text style={styles.footer} numberOfLines={1}>
                {failed ? "Couldn't refresh" : footer}
            </Text>
        </>
    )
    const testID = `report-impact-${metric.metricId}`
    if (!openUrl) {
        return (
            <View style={styles.tile} testID={testID}>
                {body}
            </View>
        )
    }
    return (
        <Pressable44
            onPress={() => openInsight(openUrl, reportId, 'tile')}
            accessibilityRole="link"
            accessibilityHint="Opens the insight"
            style={styles.tile}
            pressedStyle={styles.pressed}
            testID={testID}
        >
            {body}
        </Pressable44>
    )
}

const VALUE_SIZE = 20

const useStyles = createStyles(({ colors }) => ({
    section: {
        marginTop: 24,
    },
    grid: {
        marginTop: 10,
        gap: 10,
    },
    row: {
        flexDirection: 'row',
        gap: 10,
    },
    tileSlot: {
        flex: 1,
        minWidth: 0,
    },
    tile: {
        flex: 1,
        paddingVertical: 12,
        paddingHorizontal: 12,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
        backgroundColor: colors.surface,
    },
    pressed: {
        borderColor: colors.disabled,
    },
    valueBox: {
        height: lineHeight(VALUE_SIZE, 1.2),
        alignItems: 'flex-start',
        justifyContent: 'center',
    },
    value: {
        fontFamily: fonts.mono,
        fontSize: VALUE_SIZE,
        lineHeight: lineHeight(VALUE_SIZE, 1.2),
        fontWeight: '600',
        fontVariant: ['tabular-nums'],
        color: colors.ink,
    },
    missing: {
        color: colors.tertiary,
    },
    title: {
        ...type.meta,
        color: colors.muted,
        marginTop: 4,
    },
    footer: {
        ...type.monoSmall,
        color: colors.tertiary,
        marginTop: 6,
    },
}))
