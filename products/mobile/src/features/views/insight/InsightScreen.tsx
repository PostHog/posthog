import { type ReactElement, useMemo, useState } from 'react'
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'

import type { InsightSnapshot, PinDisplayMode, ViewEntry } from '@/model/views'
import { useChartListMotion } from '@/ui/chart/selection/ChartSelectionProvider'
import { InfoIcon } from '@/ui/icons/InfoIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, layout, radii, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { DeltaPill } from '../DeltaPill'
import { InsightChart } from '../InsightChart'
import { type DashboardSnapshot, dashboardQueryKey } from '../items'
import { OpensOnWeb } from '../OpensOnWeb'
import { PinButton } from '../PinButton'
import { useChartSheets } from '../pointSheet/ChartSheetsProvider'
import type { ChartSheetSource } from '../pointSheet/chartSheetSource'
import { RefreshFailedBanner } from '../screen/RefreshFailedBanner'
import { ViewAccessState } from '../screen/ViewAccessState'
import { VIEW_CONTENT_TOP, ViewChrome } from '../screen/ViewChrome'
import { ViewErrorState } from '../screen/ViewErrorState'
import { ViewMoreSheet } from '../screen/ViewMoreSheet'
import { ViewRangeSlot } from '../screen/ViewRangeSlot'
import { useViewBack, ViewScreenFrame } from '../screen/ViewScreenFrame'
import { ViewSkeleton } from '../screen/ViewSkeleton'
import { ViewTitle } from '../screen/ViewTitle'
import {
    deltaBasisText,
    deltaComparedText,
    insightDisplay,
    previousRangeText,
    resolvedRangeText,
    snapshotFormatter,
    valueAtText,
} from '../snapshotChart'
import { useViewsContext } from '../useViewsContext'
import { type InsightScreenState, useInsightScreen } from '../viewHooks'
import { useSnapshot } from '../viewsCache'
import { viewWebUrl } from '../webLinks'

const CHART_HEIGHT = 220

interface InsightScreenProps {
    shortId: string
    /** Opened from a dashboard tile: the dashboard's ref. */
    fromDashboard: string | null
    insightId: number | null
    from: ViewEntry
    displayMode: PinDisplayMode | null
}

/** One insight: the big number, the chart with its legend, About and the Point sheet. */
export function InsightScreen({
    shortId,
    fromDashboard,
    insightId,
    from,
    displayMode,
}: InsightScreenProps): ReactElement {
    const screen = useInsightScreen(shortId, { from, displayMode, dashboardRef: fromDashboard, insightId })
    const back = useViewBack()
    const { scope } = useViewsContext()
    const [moreOpen, setMoreOpen] = useState(false)
    const allowed = screen.access.state === 'ok'
    const loaded = Boolean(screen.insight.data)
    return (
        <ViewScreenFrame
            chrome={
                <ViewChrome
                    onBack={back}
                    refresh={allowed ? screen.refresh : null}
                    onMore={allowed && loaded ? () => setMoreOpen(true) : undefined}
                />
            }
        >
            {allowed ? (
                <InsightBody screen={screen} shortId={shortId} dashboardRef={fromDashboard} onBack={back} />
            ) : (
                <ViewAccessState access={screen.access} />
            )}
            <ViewMoreSheet
                visible={moreOpen}
                onClose={() => setMoreOpen(false)}
                webUrl={viewWebUrl(scope, `/insights/${shortId}`)}
                viewType="insight"
            />
        </ViewScreenFrame>
    )
}

interface InsightBodyProps {
    screen: InsightScreenState
    shortId: string
    dashboardRef: string | null
    onBack: () => void
}

function InsightBody({ screen, shortId, dashboardRef, onBack }: InsightBodyProps): ReactElement {
    const insets = useScreenInsets()
    const motion = useChartListMotion()
    const sheets = useChartSheets()
    const { scope } = useViewsContext()
    const dashboard = useSnapshot<DashboardSnapshot>(dashboardRef ? dashboardQueryKey(scope, dashboardRef, null) : null)
    const snapshot = screen.insight.data
    const { refresh, queryKey, itemKey } = screen
    const dashboardName = dashboard?.view.name ?? null
    const source = useMemo<ChartSheetSource | null>(
        () => (snapshot ? { snapshot, queryKey, itemKey, refreshItem: refresh.refreshItem, dashboardName } : null),
        [snapshot, queryKey, itemKey, refresh.refreshItem, dashboardName]
    )
    const contentTop = topOffset(insets, VIEW_CONTENT_TOP)
    const contentStyle = [styles.content, { paddingTop: contentTop, paddingBottom: bottomOffset(insets, 48) }]

    if (!snapshot || !source) {
        return (
            <ScrollView contentContainerStyle={[contentStyle, styles.grow]}>
                {screen.insight.isError && screen.error ? (
                    <ViewErrorState
                        kind={screen.error}
                        noun="insight"
                        match={{ kind: 'insight', ref: shortId }}
                        onRetry={() => screen.insight.refetch()}
                        onBack={onBack}
                    />
                ) : (
                    <ViewSkeleton cards={1} />
                )}
            </ScrollView>
        )
    }

    const resolved = resolvedRangeText(snapshot.resolvedRange, snapshot.interval)
    const previous = screen.comparing ? previousRangeText(snapshot) : null
    const display = insightDisplay(snapshot)
    return (
        <ScrollView
            contentContainerStyle={contentStyle}
            onScroll={motion.onScroll}
            scrollEventThrottle={16}
            refreshControl={
                <RefreshControl
                    refreshing={refresh.pulling}
                    onRefresh={refresh.onPull}
                    tintColor={colors.tertiary}
                    progressViewOffset={contentTop}
                />
            }
            testID="insight-scroll"
        >
            <ViewTitle
                eyebrow={`Insight · ${snapshot.kindLabel}`}
                title={snapshot.name}
                accessories={
                    <>
                        <Pressable44
                            onPress={() => sheets.openAbout(source, 'icon')}
                            accessibilityLabel="About this chart"
                            pressedBackground={colors.sunken}
                            style={styles.iconButton}
                            testID="view-about"
                        >
                            <InfoIcon size={22} color={colors.secondary} />
                        </Pressable44>
                        <PinButton
                            target={{
                                kind: 'insight',
                                shortId,
                                name: snapshot.name,
                                queryKind: snapshot.queryKind,
                            }}
                            match={{ kind: 'insight', ref: shortId }}
                        />
                    </>
                }
                refresh={refresh}
                range={<ViewRangeSlot label={screen.range.label} />}
                rangeDetail={resolved ? `${resolved}${previous ? ` · compared with ${previous}` : ''}` : null}
            />
            <RefreshFailedBanner status={refresh.status} />
            <View style={snapshot.refreshFailed ? styles.dimmed : undefined}>
                <Hero snapshot={snapshot} rangeLabel={screen.range.label} />
                {display === 'chart' ? (
                    <InsightChart
                        snapshot={snapshot}
                        source={source}
                        selectionId="insight"
                        rangeText={screen.range.label ?? resolved}
                        height={CHART_HEIGHT}
                        testID={`chart-${shortId}`}
                    />
                ) : display === 'web' ? (
                    <View style={styles.webCard}>
                        <OpensOnWeb shortId={shortId} />
                    </View>
                ) : null}
            </View>
        </ScrollView>
    )
}

function Hero({ snapshot, rangeLabel }: { snapshot: InsightSnapshot; rangeLabel: string | null }): ReactElement | null {
    if (snapshot.value === null) {
        return null
    }
    const formatValue = snapshotFormatter(snapshot)
    const at = valueAtText(snapshot)
    const { delta } = snapshot
    const caption = [at ? null : rangeLabel, delta ? deltaComparedText(delta, snapshot.interval) : null]
        .filter(Boolean)
        .join(' · ')
    return (
        <View style={styles.hero} testID="insight-hero">
            <View style={styles.heroRow}>
                <Text style={styles.heroValue} numberOfLines={1} adjustsFontSizeToFit>
                    {formatValue(snapshot.value)}
                </Text>
                {at ? <Text style={styles.heroAt}>{at}</Text> : null}
                {delta ? (
                    <DeltaPill
                        delta={delta}
                        formatValue={formatValue}
                        basis={deltaBasisText(delta, snapshot.interval)}
                    />
                ) : null}
            </View>
            {caption ? <Text style={styles.caption}>{caption}</Text> : null}
        </View>
    )
}

const styles = StyleSheet.create({
    content: {
        paddingHorizontal: layout.inboxGutter,
    },
    grow: {
        flexGrow: 1,
    },
    iconButton: {
        width: 40,
        height: 40,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    dimmed: {
        opacity: 0.5,
    },
    hero: {
        marginBottom: 14,
        paddingHorizontal: 2,
    },
    heroRow: {
        flexDirection: 'row',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 10,
    },
    heroValue: {
        fontSize: 40,
        lineHeight: 44,
        fontWeight: '700',
        letterSpacing: -1,
        color: colors.ink,
        fontVariant: ['tabular-nums'],
        flexShrink: 1,
    },
    heroAt: {
        ...type.metaSmall,
        color: colors.secondary,
    },
    caption: {
        ...type.metaSmall,
        color: colors.secondary,
        marginTop: 2,
    },
    webCard: {
        padding: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.white,
    },
})
