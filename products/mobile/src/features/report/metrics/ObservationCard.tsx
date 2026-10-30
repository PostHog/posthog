import { type ReactElement, useMemo } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { type MetricValueState, MISSING_VALUE } from '@/features/metrics/metricValue'
import { useChartPoints } from '@/features/metrics/useChartPoints'
import { useMetricValue } from '@/features/metrics/useMetricValue'
import { track } from '@/lib/analytics'
import type { Accent, MetricView } from '@/model/types'
import { CHART_DEFAULT_HEIGHT } from '@/ui/chart/chartMath'
import { MetricChart } from '@/ui/chart/MetricChart'
import { Eyebrow } from '@/ui/Eyebrow'
import { MonoText } from '@/ui/MonoText'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { fonts, lineHeight, radii, type } from '@/ui/tokens'

import { metricSourceLabel, valueFormatter } from './metricFooter'
import { OpenInsightLink } from './OpenInsightLink'
import { insightUrl } from './openInsight'
import { useScrubTracking } from './useScrubTracking'

interface ObservationCardProps {
    metric: MetricView
    reportId: string
    accent: Accent
}

export function ObservationCard({ metric, reportId, accent }: ObservationCardProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const value = useMetricValue(metric)
    const chart = useChartPoints(metric.data, { snapshot: metric.snapshot, interval: metric.interval })
    const onSelect = useScrubTracking(() =>
        track('mobile_report_chart_scrubbed', { report_id: reportId, chart: 'observation', metric_id: metric.metricId })
    )
    const formatValue = useMemo(() => valueFormatter(metric.format), [metric.format])
    const openUrl = insightUrl(metric.openUrl)
    return (
        <View style={styles.card} testID="report-observation">
            <Eyebrow>Observation</Eyebrow>
            <Text style={styles.title}>{metric.title}</Text>
            {metric.caption ? <Text style={styles.caption}>{metric.caption}</Text> : null}
            <ObservationValue state={value} />
            {chart.points.length > 0 ? (
                <View style={styles.chart}>
                    <MetricChart
                        points={chart.points}
                        kind={metric.chart}
                        interval={metric.interval}
                        accent={accent}
                        label={metric.title}
                        formatValue={formatValue}
                        onSelect={onSelect}
                        testID="report-observation-chart"
                    />
                </View>
            ) : chart.isLoading ? (
                <View style={[styles.chart, styles.placeholder]}>
                    <ActivityIndicator color={colors.tertiary} accessibilityLabel="Loading chart" />
                </View>
            ) : null}
            <View style={styles.footer}>
                <MonoText size={11} color={colors.tertiary} style={styles.source} numberOfLines={1}>
                    {metricSourceLabel(metric.windowLabel, metric.filterCount)}
                </MonoText>
                {openUrl ? (
                    <OpenInsightLink
                        url={openUrl}
                        reportId={reportId}
                        source="observation"
                        title={metric.title}
                        testID="report-observation-open"
                    />
                ) : null}
            </View>
        </View>
    )
}

function ObservationValue({ state }: { state: MetricValueState }): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    switch (state.kind) {
        case 'loading':
            return (
                <View style={styles.valueRow}>
                    <ActivityIndicator color={colors.tertiary} accessibilityLabel="Loading current value" />
                </View>
            )
        case 'live':
            return (
                <Text style={styles.value} testID="report-observation-value">
                    {state.text}
                </Text>
            )
        case 'saved':
            return (
                <View>
                    <Text style={styles.value} testID="report-observation-value">
                        {state.text}
                    </Text>
                    {state.measured ? <Text style={styles.note}>{state.measured}</Text> : null}
                    {state.failed ? (
                        <Text style={styles.note}>Couldn't refresh this metric. Showing the latest saved value.</Text>
                    ) : null}
                </View>
            )
        case 'missing':
            return (
                <View>
                    <Text style={[styles.value, styles.missing]}>{MISSING_VALUE}</Text>
                    {state.failed ? (
                        <View style={styles.retryRow}>
                            <Text style={styles.note}>Couldn't load this metric.</Text>
                            <Pressable44
                                onPress={() => void state.retry()}
                                accessibilityLabel="Try loading the metric again"
                                pressedStyle={styles.pressed}
                            >
                                <Text style={styles.retry}>Try again</Text>
                            </Pressable44>
                        </View>
                    ) : null}
                </View>
            )
    }
}

const VALUE_SIZE = 28

const useStyles = createStyles(({ colors }) => ({
    card: {
        marginTop: 24,
        padding: 14,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
        backgroundColor: colors.surface,
    },
    title: {
        ...type.bodySmallStrong,
        color: colors.ink,
        marginTop: 8,
    },
    caption: {
        ...type.meta,
        color: colors.secondary,
        marginTop: 2,
    },
    valueRow: {
        marginTop: 10,
        height: lineHeight(VALUE_SIZE, 1.2),
        alignItems: 'flex-start',
        justifyContent: 'center',
    },
    value: {
        marginTop: 10,
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
    note: {
        ...type.meta,
        color: colors.secondary,
        marginTop: 2,
    },
    retryRow: {
        flexDirection: 'row',
        alignItems: 'baseline',
        gap: 8,
    },
    retry: {
        ...type.meta,
        fontWeight: '600',
        color: colors.blue,
        marginTop: 2,
    },
    pressed: {
        opacity: 0.6,
    },
    chart: {
        marginTop: 14,
    },
    placeholder: {
        height: CHART_DEFAULT_HEIGHT,
        alignItems: 'center',
        justifyContent: 'center',
    },
    footer: {
        marginTop: 12,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
    },
    source: {
        flexShrink: 1,
    },
}))
