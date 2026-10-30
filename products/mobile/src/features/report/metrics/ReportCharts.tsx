import { type ReactElement, useMemo } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { useChartPoints } from '@/features/metrics/useChartPoints'
import { track } from '@/lib/analytics'
import type { Accent, ReportChartView } from '@/model/types'
import { CHART_DEFAULT_HEIGHT } from '@/ui/chart/chartMath'
import { MetricChart } from '@/ui/chart/MetricChart'
import { Eyebrow } from '@/ui/Eyebrow'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { valueFormatter } from './metricFooter'
import { OpenInsightLink } from './OpenInsightLink'
import { insightUrl } from './openInsight'
import { useScrubTracking } from './useScrubTracking'

interface ReportChartsProps {
    charts: ReportChartView[]
    reportId: string
    accent: Accent
}

export function ReportCharts({ charts, reportId, accent }: ReportChartsProps): ReactElement | null {
    const styles = useStyles()
    if (charts.length === 0) {
        return null
    }
    return (
        <View style={styles.section} testID="report-charts">
            <Eyebrow>Charts</Eyebrow>
            {charts.map((chart) => (
                <ChartCard key={chart.chartId} chart={chart} reportId={reportId} accent={accent} />
            ))}
        </View>
    )
}

interface ChartCardProps {
    chart: ReportChartView
    reportId: string
    accent: Accent
}

function ChartCard({ chart, reportId, accent }: ChartCardProps): ReactElement {
    const styles = useStyles()
    const openUrl = insightUrl(chart.openUrl)
    return (
        <View style={styles.card} testID={`report-chart-${chart.chartId}`}>
            <Text style={styles.title}>{chart.title}</Text>
            {chart.caption ? <Text style={styles.caption}>{chart.caption}</Text> : null}
            {chart.data ? <DrawnChart chart={chart} reportId={reportId} accent={accent} /> : null}
            {openUrl ? (
                <View style={styles.footer}>
                    <OpenInsightLink url={openUrl} reportId={reportId} source="chart" title={chart.title} />
                </View>
            ) : null}
        </View>
    )
}

function DrawnChart({ chart, reportId, accent }: ChartCardProps): ReactElement | null {
    const styles = useStyles()
    const colors = useColors()
    const state = useChartPoints(chart.data)
    const formatValue = useMemo(() => valueFormatter(chart.format), [chart.format])
    const onSelect = useScrubTracking(() =>
        track('mobile_report_chart_scrubbed', { report_id: reportId, chart: 'chart', chart_id: chart.chartId })
    )
    if (state.points.length > 0) {
        return (
            <View style={styles.chart}>
                <MetricChart
                    points={state.points}
                    kind={chart.chart}
                    interval={chart.interval}
                    accent={accent}
                    label={chart.title}
                    formatValue={formatValue}
                    onSelect={onSelect}
                    testID={`report-chart-${chart.chartId}-canvas`}
                />
            </View>
        )
    }
    if (state.isLoading) {
        return (
            <View style={[styles.chart, styles.placeholder]}>
                <ActivityIndicator color={colors.tertiary} accessibilityLabel="Loading chart" />
            </View>
        )
    }
    const failed = insightUrl(chart.openUrl)
        ? "Couldn't load this chart. Open the insight to see it."
        : "Couldn't load this chart."
    const message = state.isError ? failed : 'No data in this window.'
    return <Text style={styles.note}>{message}</Text>
}

const useStyles = createStyles(({ colors }) => ({
    section: {
        marginTop: 24,
    },
    card: {
        marginTop: 10,
        padding: 14,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
        backgroundColor: colors.surface,
    },
    title: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    caption: {
        ...type.meta,
        color: colors.secondary,
        marginTop: 2,
    },
    chart: {
        marginTop: 14,
    },
    placeholder: {
        height: CHART_DEFAULT_HEIGHT,
        alignItems: 'center',
        justifyContent: 'center',
    },
    note: {
        ...type.meta,
        color: colors.secondary,
        marginTop: 10,
    },
    footer: {
        marginTop: 12,
        flexDirection: 'row',
        justifyContent: 'flex-end',
    },
}))
