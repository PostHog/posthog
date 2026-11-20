import { useQuery, useQueryClient } from '@tanstack/react-query'
import { memo, type ReactElement, type ReactNode, useEffect, useId, useMemo } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'
import { stableStringify } from '@/api/query'
import { scopeKey } from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import {
    insightDisplay,
    insightRenderState,
    noDataText,
    queryDisplay,
    snapshotBarLayout,
    snapshotChartSeries,
    snapshotFormatter,
} from '@/features/views/snapshotChart'
import type { InsightSnapshot } from '@/model/views'
import { BarList } from '@/ui/chart/BarList'
import { ChartLegend, useChartLegend } from '@/ui/chart/ChartLegend'
import { FunnelSteps } from '@/ui/chart/FunnelSteps'
import { MetricChart } from '@/ui/chart/MetricChart'
import { RetentionGrid } from '@/ui/chart/RetentionGrid'
import { SqlTable } from '@/ui/chart/SqlTable'
import type { ChartCanvasSlot } from '@/ui/chart/types'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'
import { queuedChartRead, releaseChartRead, useChatChartResource } from './ChatChartResources'
import { readChatVisualization } from './chatVisualizationRead'
import { visualizationQuery, visualizationSnapshot, visualizationUrl } from './visualizationModel'
import { openReplyUrl } from './webLinks'

export interface ChatVisualizationProps {
    query?: unknown
    shortId?: string
    title?: string
    result?: unknown
    visualizationId?: string
    webUrl?: string
    children?: ReactNode
}

const VisualizationResult = memo(function VisualizationResult({
    snapshot,
    selectionId,
    canvasSlot,
}: {
    snapshot: InsightSnapshot
    selectionId: string
    canvasSlot?: ChartCanvasSlot
}): ReactElement {
    const styles = useStyles()
    const { chartPalette } = useTheme()
    const legend = useChartLegend()
    const series = useMemo(() => snapshotChartSeries(snapshot, chartPalette), [snapshot, chartPalette])
    const display = insightDisplay(snapshot)
    const state = insightRenderState(snapshot)
    const formatValue = snapshotFormatter(snapshot)
    if (display === 'web') return <Text style={styles.detail}>Open this chart on the web to view it.</Text>
    if (state === 'pending') return <Text style={styles.detail}>Chart data is unavailable. Open it on the web.</Text>
    if (state === 'empty') return <Text style={styles.detail}>{noDataText(snapshot)}</Text>
    switch (display) {
        case 'number':
            return <Text style={styles.value}>{snapshot.value === null ? '–' : formatValue(snapshot.value)}</Text>
        case 'chart':
            return (
                <View style={styles.chart}>
                    <MetricChart
                        series={series}
                        kind={snapshot.chartKind ?? 'line'}
                        barLayout={snapshotBarLayout(snapshot)}
                        interval={snapshot.interval}
                        label={snapshot.name}
                        formatValue={formatValue}
                        variant="inline"
                        height={200}
                        selectionId={selectionId}
                        trackingContext="chat"
                        canvasSlot={canvasSlot}
                        hiddenKeys={legend.state.hiddenKeys}
                        testID="chat-visualization-chart"
                    />
                    {series.length > 1 ? (
                        <ChartLegend
                            series={series}
                            state={legend.state}
                            onChange={legend.setState}
                            selectionId={selectionId}
                        />
                    ) : null}
                </View>
            )
        case 'funnel':
            if (snapshot.funnel)
                return (
                    <FunnelSteps
                        funnel={snapshot.funnel}
                        label={snapshot.name}
                        selectionId={selectionId}
                        trackingContext="chat"
                    />
                )
            break
        case 'retention':
            if (snapshot.retention)
                return (
                    <RetentionGrid
                        retention={snapshot.retention}
                        label={snapshot.name}
                        selectionId={selectionId}
                        trackingContext="chat"
                    />
                )
            break
        case 'bars':
            if (snapshot.ranking)
                return (
                    <BarList
                        ranking={snapshot.ranking}
                        label={snapshot.name}
                        formatValue={formatValue}
                        maxRows={6}
                        selectionId={selectionId}
                        trackingContext="chat"
                    />
                )
            break
        case 'table':
            if (snapshot.sqlTable)
                return (
                    <SqlTable
                        table={snapshot.sqlTable}
                        label={snapshot.name}
                        maxRows={6}
                        selectionId={selectionId}
                        trackingContext="chat"
                    />
                )
            break
    }
    return <Text style={styles.detail}>Open this chart on the web to view it.</Text>
})

export function ChatVisualization({
    query,
    shortId,
    title,
    result,
    visualizationId,
    webUrl,
    children,
}: ChatVisualizationProps): ReactElement {
    const styles = useStyles()
    const scope = useProjectScope()
    const resource = useChatChartResource()
    const instanceId = useId()
    const client = useQueryClient()
    const normalizedQuery = useMemo(() => visualizationQuery(query), [query])
    const supported = !!shortId || (!!query && queryDisplay(normalizedQuery) !== 'web')
    const inline = useMemo(() => {
        if (!query || result === undefined || result === null) return undefined
        const snapshot = visualizationSnapshot(normalizedQuery, result, title)
        return snapshot.lastRefreshAt ? snapshot : undefined
    }, [query, normalizedQuery, result, title])
    const queryKey = ['chat-visualization', ...scopeKey(scope), shortId, stableStringify(normalizedQuery), title]
    const enabled = !!scope && resource.visible && supported && !inline
    const data = useQuery({
        queryKey,
        queryFn: () => {
            const owner = client.getQueryCache().find({ queryKey, exact: true })
            if (!owner) throw new Error('Chart query unavailable')
            return queuedChartRead(owner, shortId ? 'insights' : 'query', (signal) =>
                readChatVisualization({
                    query: normalizedQuery,
                    shortId,
                    title,
                    scope,
                    signal,
                    onCached: (snapshot) => {
                        if (!signal.aborted && client.getQueryCache().find({ queryKey, exact: true }) === owner)
                            client.setQueryData(queryKey, snapshot)
                    },
                })
            )
        },
        enabled,
        staleTime: 5 * 60_000,
        retry: false,
    })
    const owner = client.getQueryCache().find({ queryKey, exact: true })
    useEffect(() => {
        if (owner && !enabled) releaseChartRead(owner)
        return () => {
            if (owner) releaseChartRead(owner)
        }
    }, [owner, enabled])
    const snapshot = inline ?? data.data
    const url =
        webUrl ??
        (scope ? visualizationUrl(normalizedQuery, `${scope.host}/project/${scope.projectId}`, shortId) : undefined)
    const loading = !inline && supported && data.isLoading
    const unavailable = snapshot === null
    return (
        <View ref={resource.ref} onLayout={resource.onLayout} style={styles.card} testID="chat-visualization">
            <Text style={styles.meta}>{shortId ? 'Insight' : 'Chart'}</Text>
            <Text style={styles.title} numberOfLines={2}>
                {title || snapshot?.name || (loading ? 'Loading insight…' : 'Chart')}
            </Text>
            {snapshot?.description ? <Text style={styles.detail}>{snapshot.description}</Text> : null}
            {loading ? (
                <ActivityIndicator accessibilityLabel="Loading chart" />
            ) : snapshot ? (
                <VisualizationResult
                    snapshot={snapshot}
                    selectionId={`chat-${visualizationId ?? instanceId}`}
                    canvasSlot={resource.canvasSlot}
                />
            ) : (
                <Text style={styles.detail}>
                    {data.isError
                        ? 'Could not load chart. Open it on the web or try again.'
                        : unavailable
                          ? 'Insight unavailable'
                          : 'Open this chart on the web to view it.'}
                </Text>
            )}
            {snapshot && (data.isError || snapshot.refreshFailed) ? (
                <Text style={styles.detail}>Could not refresh chart. Showing cached data.</Text>
            ) : null}
            {data.isError || snapshot?.refreshFailed ? (
                <Pressable44
                    style={styles.action}
                    accessibilityRole="button"
                    disabled={data.isFetching}
                    onPress={() => void data.refetch()}
                >
                    <Text style={styles.link}>{data.isFetching ? 'Loading chart…' : 'Try again'}</Text>
                </Pressable44>
            ) : null}
            {children}
            {url ? (
                <Pressable44
                    style={styles.action}
                    accessibilityRole="link"
                    onPress={() => openReplyUrl(url, 'insight_card', { objectKind: 'insight' })}
                >
                    <Text style={styles.link}>{shortId ? 'Open insight' : 'Open chart on web'}</Text>
                </Pressable44>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        backgroundColor: colors.surface,
        borderColor: colors.hairline,
        borderWidth: 1,
        borderRadius: radii.card,
        padding: 12,
        gap: 10,
        marginBottom: 10,
    },
    meta: { ...type.meta, color: colors.secondary },
    title: { ...type.bodyStrong, color: colors.ink },
    detail: { ...type.bodySmall, color: colors.muted },
    value: { ...type.sheetTitleLarge, color: colors.ink },
    link: { ...type.bodySmallStrong, color: colors.blue },
    action: { minHeight: 34, justifyContent: 'center' },
    chart: { gap: 12 },
}))
