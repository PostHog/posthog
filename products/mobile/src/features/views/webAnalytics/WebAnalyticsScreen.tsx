import { type ReactElement, useState } from 'react'
import { RefreshControl, ScrollView, Text, View } from 'react-native'
import { formatMetricValue } from '@/model/adapters/metric'
import type { NumberDelta, ViewEntry, WebOverviewMetric } from '@/model/views'
import { useChartListMotion } from '@/ui/chart/selection/ChartSelectionProvider'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { layout, radii, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { type ScrollTitleState, useScrollTitle } from '@/ui/useScrollTitle'

import { DeltaPill } from '../DeltaPill'
import { PinButton } from '../PinButton'
import { ViewRangeControl } from '../range/ViewRangeControl'
import { RefreshFailedBanner } from '../screen/RefreshFailedBanner'
import { ViewChrome } from '../screen/ViewChrome'
import { ViewErrorState } from '../screen/ViewErrorState'
import { ViewMoreSheet } from '../screen/ViewMoreSheet'
import { useViewBack, ViewScreenFrame } from '../screen/ViewScreenFrame'
import { ViewSkeleton } from '../screen/ViewSkeleton'
import { ViewTitle } from '../screen/ViewTitle'
import { resolvedRangeText } from '../snapshotChart'
import { useViewsContext } from '../useViewsContext'
import { ViewsReauthState } from '../ViewsReauthState'
import { useWebAnalyticsScreen, type WebAnalyticsScreenState } from '../viewHooks'
import { viewWebUrl } from '../webLinks'

/** The web analytics overview numbers, each with its change from the previous period, as the web's overview tile. */
export function WebAnalyticsScreen({ from }: { from: ViewEntry }): ReactElement {
    const screen = useWebAnalyticsScreen({ from })
    const scrollTitle = useScrollTitle('Web analytics')
    const back = useViewBack()
    const { scope } = useViewsContext()
    const [moreOpen, setMoreOpen] = useState(false)
    const allowed = screen.access.state === 'ok'
    return (
        <ViewScreenFrame
            chrome={
                <ViewChrome
                    title={scrollTitle.title}
                    onBack={back}
                    onMore={allowed ? () => setMoreOpen(true) : undefined}
                />
            }
        >
            {allowed ? (
                <WebAnalyticsBody scrollTitle={scrollTitle} screen={screen} onBack={back} />
            ) : (
                <ViewsReauthState access={screen.access} />
            )}
            <ViewMoreSheet
                visible={moreOpen}
                onClose={() => setMoreOpen(false)}
                webUrl={viewWebUrl(scope, '/web')}
                viewType="web_analytics"
            />
        </ViewScreenFrame>
    )
}

function WebAnalyticsBody({
    screen,
    onBack,
    scrollTitle,
}: {
    screen: WebAnalyticsScreenState
    onBack: () => void
    scrollTitle: ScrollTitleState
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    const motion = useChartListMotion()
    const { refresh } = screen
    const overview = screen.overview.data
    const contentTop = topOffset(insets, SCREEN_CONTENT_TOP)
    const contentStyle = [styles.content, { paddingTop: contentTop, paddingBottom: bottomOffset(insets, 48) }]
    const rangeDetail = overview ? resolvedRangeText(overview.resolvedRange, 'day') : null
    const title = (
        <ViewTitle
            onTitleLayout={scrollTitle.onTitleLayout}
            title="Web analytics"
            accessories={<PinButton target={{ kind: 'web_analytics' }} match={{ kind: 'web_analytics', ref: null }} />}
            refresh={refresh}
            range={
                // No compare row: the overview always compares with the previous period, as the web's overview tile does.
                <ViewRangeControl
                    range={screen.range}
                    resolved={overview?.resolvedRange ?? null}
                    loading={screen.rangeLoading}
                    detail={rangeDetail}
                    compare={null}
                />
            }
            rangeDetail={rangeDetail}
        />
    )

    if (!overview) {
        return (
            <ScrollView contentContainerStyle={[contentStyle, styles.grow]}>
                {screen.overview.isError && screen.error ? (
                    <ViewErrorState
                        kind={screen.error}
                        noun="view"
                        match={{ kind: 'web_analytics', ref: null }}
                        onRetry={() => screen.overview.refetch()}
                        onBack={onBack}
                    />
                ) : (
                    <ViewSkeleton cards={2} />
                )}
            </ScrollView>
        )
    }

    return (
        <ScrollView
            contentContainerStyle={contentStyle}
            onScroll={(event) => {
                motion.onScroll()
                scrollTitle.onScroll(event)
            }}
            scrollEventThrottle={16}
            refreshControl={
                <RefreshControl
                    refreshing={refresh.pulling}
                    onRefresh={refresh.onPull}
                    tintColor={colors.tertiary}
                    progressBackgroundColor={colors.surface}
                    colors={[colors.tertiary]}
                    progressViewOffset={contentTop}
                />
            }
            testID="web-analytics-scroll"
        >
            {title}
            <RefreshFailedBanner status={refresh.status} />
            {overview.metrics.length === 0 ? (
                <Text style={styles.empty}>No web analytics data for this range.</Text>
            ) : (
                <View style={[styles.grid, overview.refreshFailed && styles.dimmed]}>
                    {pairs(overview.metrics).map(([left, right]) => (
                        <View key={left.key} style={styles.gridRow}>
                            <MetricCard metric={left} />
                            {right ? <MetricCard metric={right} /> : <View style={styles.cardSpacer} />}
                        </View>
                    ))}
                </View>
            )}
            {overview.metrics.length > 0 ? (
                <Text style={styles.footnote}>Changes compare with the previous period of the same length.</Text>
            ) : null}
        </ScrollView>
    )
}

/** Two cards per row, so an odd last card keeps the width of the others. */
function pairs(metrics: WebOverviewMetric[]): [WebOverviewMetric, WebOverviewMetric | undefined][] {
    const rows: [WebOverviewMetric, WebOverviewMetric | undefined][] = []
    for (let index = 0; index < metrics.length; index += 2) {
        const left = metrics[index]
        if (left) {
            rows.push([left, metrics[index + 1]])
        }
    }
    return rows
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

function MetricCard({ metric }: { metric: WebOverviewMetric }): ReactElement {
    const styles = useStyles()
    const formatValue = (value: number): string =>
        formatMetricValue(value, metric.format.valueFormat, metric.format.unit)
    const delta = changeDelta(metric)
    return (
        <View style={styles.card} testID={`web-metric-${metric.key.replace(/\s+/g, '-')}`}>
            <Text style={styles.cardTitle} numberOfLines={1}>
                {metric.label}
            </Text>
            <Text style={styles.cardValue} numberOfLines={1} adjustsFontSizeToFit>
                {metric.value === null ? '–' : formatValue(metric.value)}
            </Text>
            {delta ? <DeltaPill delta={delta} formatValue={formatValue} basis="vs previous period" /> : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: {
        paddingHorizontal: layout.inboxGutter,
    },
    grow: {
        flexGrow: 1,
    },
    grid: {
        gap: 10,
    },
    gridRow: {
        flexDirection: 'row',
        gap: 10,
    },
    cardSpacer: {
        flex: 1,
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
    cardTitle: {
        ...type.meta,
        color: colors.muted,
    },
    cardValue: {
        fontSize: 24,
        lineHeight: 29,
        fontWeight: '700',
        letterSpacing: -0.4,
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    empty: {
        ...type.bodySmall,
        color: colors.muted,
        textAlign: 'center',
        paddingVertical: 32,
    },
    footnote: {
        ...type.meta,
        color: colors.tertiary,
        marginTop: 14,
        paddingHorizontal: 2,
    },
}))
