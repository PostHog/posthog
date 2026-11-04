import { memo, type ReactElement, type ReactNode, useEffect } from 'react'
import { Text, View } from 'react-native'
import Animated, {
    cancelAnimation,
    Easing,
    useAnimatedStyle,
    useReducedMotion,
    useSharedValue,
    withRepeat,
    withTiming,
} from 'react-native-reanimated'
import type { RowAnchor } from '@/features/inbox/contextMenuPlacement'
import { useNow } from '@/lib/useNow'
import type { InsightSnapshot, PinView } from '@/model/views'
import { ChartLegend, useChartLegend } from '@/ui/chart/ChartLegend'
import { MetricChart } from '@/ui/chart/MetricChart'
import { Sparkline } from '@/ui/chart/Sparkline'
import type { ChartTooltipPoint } from '@/ui/chart/types'
import { COMPACT_CHART_HEIGHT } from '@/ui/chart/variant'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors, useTheme } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'
import { DeltaPill, deltaSpoken } from '../DeltaPill'
import { statusLine } from '../freshness'
import { type DashboardSnapshot, dashboardQueryKey } from '../items'
import { type PinData, usePinData } from '../pinHooks'
import { deltaBasisText, snapshotChartSeries, snapshotFormatter, valueAtText } from '../snapshotChart'
import { useViewsContext } from '../useViewsContext'
import { itemErrorMessage } from '../viewHooks'
import { useSnapshot } from '../viewsCache'
import { dataUntil } from './pinChart'
import { useMenuTrigger } from './useMenuTrigger'
import { ViewIcon, viewTypeLabel } from './viewMeta'

const HEAD_HEIGHT = 62
const NUMBER_BODY_HEIGHT = 50
const VALUE_ROW_HEIGHT = 33
const CHART_BOTTOM = 14
const FOOTER_HEIGHT = 42
export const PIN_ROW_HEIGHT = HEAD_HEIGHT + 2
export const PIN_NUMBER_HEIGHT = HEAD_HEIGHT + NUMBER_BODY_HEIGHT + FOOTER_HEIGHT + 2
export const PIN_CHART_HEIGHT = HEAD_HEIGHT + VALUE_ROW_HEIGHT + COMPACT_CHART_HEIGHT + CHART_BOTTOM + FOOTER_HEIGHT + 2

const SPARKLINE_BUCKETS = 14
/** The sparkline draws the last 7 buckets in blue and the ones before them in gray. */
const SPARKLINE_CURRENT = 7

export interface PinCardProps {
    pin: PinView
    /** Position in the whole list, for the canvas budget. */
    index: number
    /** Demo mode: pins that open on the web cannot open. */
    demo: boolean
    onOpen: (pin: PinView) => void
    onMenu: (pin: PinView, anchor: RowAnchor) => void
    onChooseTile: (pin: PinView) => void
    onUnpin: (pin: PinView) => void
    /** A tap on a Chart pin's pinned tooltip. Without it the tooltip takes no touches. */
    onPressTooltip?: (pin: PinView, snapshot: InsightSnapshot, point: ChartTooltipPoint) => void
}

export function pinTestId(pin: Pick<PinView, 'kind' | 'ref'>, part?: 'value'): string {
    return ['views-pin', part, pin.kind, pin.ref].filter(Boolean).join('-')
}

/** One pin as its display mode shows it. */
export const PinCard = memo(function PinCard(props: PinCardProps): ReactElement {
    if (props.pin.display.mode === 'row' || !props.pin.native) {
        return <RowPin {...props} />
    }
    return <DataPin {...props} />
})

function rowSecondLine(pin: PinView, demo: boolean): string {
    const label = viewTypeLabel(pin.kind)
    if (pin.native) {
        return label ?? ''
    }
    if (demo) {
        return 'Not available in the demo'
    }
    return label ? `${label} · Opens on the web` : 'Opens on the web'
}

function RowPin({ pin, demo, onOpen, onMenu }: PinCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const menu = useMenuTrigger(pin, onMenu)
    const unavailable = !pin.native && demo
    const second = rowSecondLine(pin, demo)
    return (
        <View ref={menu.ref} style={[styles.card, { height: PIN_ROW_HEIGHT }]} testID={pinTestId(pin)}>
            <Pressable44
                onPress={() => onOpen(pin)}
                onLongPress={menu.onLongPress}
                accessibilityActions={menu.accessibilityActions}
                onAccessibilityAction={menu.onAccessibilityAction}
                disabled={unavailable}
                accessibilityLabel={`${pin.name}, ${second}`}
                accessibilityState={{ disabled: unavailable }}
                pressedBackground={colors.sunken}
                style={styles.head}
            >
                <PinHeadContent pin={pin} second={second} dim={unavailable} />
                {pin.native ? (
                    <ChevronRightIcon size={13} color={colors.tertiary} />
                ) : (
                    <ExternalLinkIcon size={16} color={unavailable ? colors.disabled : colors.tertiary} />
                )}
            </Pressable44>
        </View>
    )
}

function PinHeadContent({ pin, second, dim = false }: { pin: PinView; second: string; dim?: boolean }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <>
            <View style={styles.iconTile}>
                <ViewIcon kind={pin.kind} color={dim ? colors.disabled : colors.muted} />
            </View>
            <View style={styles.headText}>
                <Text style={[styles.title, dim && styles.dimText]} numberOfLines={1}>
                    {pin.name}
                </Text>
                <Text style={styles.meta} numberOfLines={1}>
                    {second}
                </Text>
            </View>
        </>
    )
}

/**
 * A dashboard pin's tile is gone when its insight read answers 404, or when the cached dashboard has no tile with
 * that id any more.
 */
function useTileRemoved(pin: PinView, data: PinData): boolean {
    const context = useViewsContext()
    const dashboard = useSnapshot<DashboardSnapshot>(
        pin.kind === 'dashboard' && pin.ref ? dashboardQueryKey(context.scope, pin.ref, null) : null
    )
    if (pin.kind !== 'dashboard') {
        return false
    }
    const tileId = pin.display.tileId
    const missing =
        dashboard !== undefined &&
        typeof tileId === 'number' &&
        !dashboard.view.tiles.some((tile) => tile.tileId === tileId)
    return data.tileRemoved || missing
}

function DataPin(props: PinCardProps): ReactElement {
    const { pin } = props
    const data = usePinData(pin)
    const tileRemoved = useTileRemoved(pin, data)
    if (tileRemoved) {
        return <RemovedTilePin {...props} />
    }
    return pin.display.mode === 'chart' ? <ChartPin {...props} data={data} /> : <NumberPin {...props} data={data} />
}

function dataSecondLine(pin: PinView, data: PinData): string {
    if (pin.kind === 'dashboard') {
        return data.snapshot ? data.snapshot.name : 'Dashboard'
    }
    return viewTypeLabel(pin.kind) ?? ''
}

function RemovedTilePin({ pin, onMenu, onChooseTile }: PinCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const menu = useMenuTrigger(pin, onMenu)
    return (
        <View ref={menu.ref} style={styles.card} testID={pinTestId(pin)}>
            <Pressable44
                onPress={() => onChooseTile(pin)}
                onLongPress={menu.onLongPress}
                accessibilityActions={menu.accessibilityActions}
                onAccessibilityAction={menu.onAccessibilityAction}
                accessibilityLabel={`${pin.name}. The chosen tile was removed. Choose another.`}
                accessibilityHint="Opens the tile list"
                pressedBackground={colors.sunken}
                style={styles.head}
            >
                <View style={styles.iconTile}>
                    <ViewIcon kind={pin.kind} />
                </View>
                <View style={styles.headText}>
                    <Text style={styles.title} numberOfLines={1}>
                        {pin.name}
                    </Text>
                    <Text style={styles.meta}>The chosen tile was removed. Choose another.</Text>
                </View>
                <Text style={styles.textAction}>Choose tile</Text>
            </Pressable44>
        </View>
    )
}

interface DataPinProps extends PinCardProps {
    data: PinData
}

function NumberPin({ pin, data, onOpen, onMenu, onUnpin }: DataPinProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const menu = useMenuTrigger(pin, onMenu)
    const { snapshot } = data
    const second = dataSecondLine(pin, data)
    const format = snapshot ? snapshotFormatter(snapshot) : null
    const value = snapshot && format && snapshot.value !== null ? format(snapshot.value) : null
    const delta = snapshot && format ? pinDelta(snapshot, format) : null
    const at = snapshot ? valueAtText(snapshot) : null
    const values = (snapshot?.series?.points ?? []).slice(-SPARKLINE_BUCKETS).map((point) => point.value)
    const label = [pin.name, value, delta?.spoken, second].filter(Boolean).join(', ')
    return (
        <View ref={menu.ref} style={styles.card} testID={pinTestId(pin)}>
            <Pressable44
                onPress={() => onOpen(pin)}
                onLongPress={menu.onLongPress}
                accessibilityActions={menu.accessibilityActions}
                onAccessibilityAction={menu.onAccessibilityAction}
                accessibilityLabel={label}
                pressedBackground={colors.sunken}
            >
                <View style={styles.head}>
                    <PinHeadContent pin={pin} second={second} />
                </View>
                <View style={styles.numberBody}>
                    <DataState data={data} capable={snapshot?.capabilities.number ?? true} onUnpin={() => onUnpin(pin)}>
                        <View style={[styles.valueColumn, snapshot?.refreshFailed && styles.stale]}>
                            <Text style={styles.bigValue} numberOfLines={1} testID={pinTestId(pin, 'value')}>
                                {value ?? '–'}
                            </Text>
                            {delta || at ? (
                                <View style={styles.deltaRow}>
                                    {delta ? <DeltaPill {...delta.props} /> : null}
                                    {at ? <Text style={styles.meta}>{at}</Text> : null}
                                </View>
                            ) : null}
                        </View>
                        {values.length > 1 ? (
                            <View style={snapshot?.refreshFailed && styles.stale}>
                                <Sparkline values={values} highlightFrom={values.length - SPARKLINE_CURRENT} />
                            </View>
                        ) : null}
                    </DataState>
                </View>
                <PinDataFooter data={data} />
            </Pressable44>
            <ProgressLine active={data.updating} />
        </View>
    )
}

function ChartPin({ pin, index, data, onOpen, onMenu, onUnpin, onPressTooltip }: DataPinProps): ReactElement {
    const { colors, chartPalette } = useTheme()
    const styles = useStyles()
    const menu = useMenuTrigger(pin, onMenu)
    const legend = useChartLegend()
    const { snapshot } = data
    const second = dataSecondLine(pin, data)
    const format = snapshot ? snapshotFormatter(snapshot) : null
    const value = snapshot && format && snapshot.value !== null ? format(snapshot.value) : null
    const delta = snapshot && format ? pinDelta(snapshot, format) : null
    const at = snapshot ? valueAtText(snapshot) : null
    const series = snapshot ? snapshotChartSeries(snapshot, chartPalette) : []
    const showValue = !snapshot || snapshot.capabilities.number
    const canChart = snapshot ? snapshot.capabilities.chart && series.length > 0 : true
    const slotKey = `pin:${pin.shortcutId}`
    return (
        <View ref={menu.ref} style={styles.card} testID={pinTestId(pin)}>
            <Pressable44
                onPress={() => onOpen(pin)}
                onLongPress={menu.onLongPress}
                accessibilityActions={menu.accessibilityActions}
                onAccessibilityAction={menu.onAccessibilityAction}
                accessibilityLabel={[pin.name, value, delta?.spoken, second].filter(Boolean).join(', ')}
                accessibilityHint="Opens the view"
                pressedBackground={colors.sunken}
            >
                <View style={styles.head}>
                    <PinHeadContent pin={pin} second={second} />
                </View>
                {showValue ? (
                    <View style={[styles.valueRow, snapshot?.refreshFailed && styles.stale]}>
                        {snapshot || data.error ? (
                            <>
                                <Text style={styles.chartValue} numberOfLines={1} testID={pinTestId(pin, 'value')}>
                                    {value ?? '–'}
                                </Text>
                                {at ? <Text style={styles.meta}>{at}</Text> : null}
                                {delta ? <DeltaPill {...delta.props} /> : null}
                            </>
                        ) : (
                            <View style={[styles.skeleton, styles.skeletonValue]} />
                        )}
                    </View>
                ) : null}
            </Pressable44>
            <View style={[styles.chartArea, snapshot?.refreshFailed && styles.stale]}>
                <DataState data={data} capable={canChart} onUnpin={() => onUnpin(pin)} chart>
                    {snapshot && format ? (
                        <MetricChart
                            series={series}
                            hiddenKeys={legend.state.hiddenKeys}
                            kind={snapshot.chartKind ?? 'line'}
                            interval={snapshot.interval}
                            label={snapshot.name}
                            formatValue={format}
                            variant="compact"
                            dataUntil={dataUntil(snapshot)}
                            canvasSlot={{ key: slotKey, index }}
                            selectionId={slotKey}
                            trackingContext="pin"
                            accessibilitySummary={[
                                `${snapshot.name}, ${snapshot.chartKind ?? 'line'} chart`,
                                data.rangeLabel,
                                value ? `Latest ${value}` : null,
                            ]
                                .filter(Boolean)
                                .join('. ')}
                            onPressTooltip={
                                onPressTooltip ? (point) => onPressTooltip(pin, snapshot, point) : undefined
                            }
                            testID={`chart-${pinTestId(pin)}`}
                        />
                    ) : null}
                </DataState>
            </View>
            {canChart && series.length > 1 ? (
                <View style={[styles.legend, snapshot?.refreshFailed && styles.stale]}>
                    <ChartLegend
                        series={series}
                        state={legend.state}
                        onChange={legend.setState}
                        onPressMore={() => onOpen(pin)}
                        selectionId={slotKey}
                        testID={`chart-${pinTestId(pin)}-legend`}
                    />
                </View>
            ) : null}
            <PinDataFooter data={data} />
            <ProgressLine active={data.updating} />
        </View>
    )
}

function PinDataFooter({ data }: { data: PinData }): ReactElement | null {
    const styles = useStyles()
    useNow()
    const freshness = statusLine([data.snapshot], data.updating).text
    if (!data.rangeLabel && !freshness) {
        return null
    }
    return (
        <View style={styles.footer}>
            {data.rangeLabel ? (
                <Text style={styles.meta} numberOfLines={1}>
                    {data.rangeLabel}
                </Text>
            ) : null}
            {freshness ? (
                <Text style={styles.meta} numberOfLines={1}>
                    {freshness}
                </Text>
            ) : null}
        </View>
    )
}

interface DataStateProps {
    data: PinData
    /** False when the view has no number or line to show in this mode. */
    capable: boolean
    onUnpin: () => void
    chart?: boolean
    children: ReactNode
}

/** The body of a Number or Chart pin: the data, a placeholder while it loads, or why it cannot show. */
function DataState({ data, capable, onUnpin, chart = false, children }: DataStateProps): ReactElement {
    const styles = useStyles()
    if (data.snapshot && capable) {
        return <>{children}</>
    }
    if (data.snapshot) {
        return (
            <Text style={styles.stateText}>
                {chart
                    ? 'This view has no line to draw. Show it as a number or a row.'
                    : 'This view has no single number. Show it as a chart or a row.'}
            </Text>
        )
    }
    if (data.error && data.error !== 'scope') {
        const removable = data.error === 'deleted' || data.error === 'no_access'
        return (
            <View style={styles.stateRow}>
                <Text style={[styles.stateText, styles.stateGrow]}>{itemErrorMessage(data.error)}</Text>
                {removable ? (
                    <Pressable44 onPress={onUnpin} accessibilityLabel="Unpin" style={styles.textButton}>
                        <Text style={styles.textAction}>Unpin</Text>
                    </Pressable44>
                ) : null}
            </View>
        )
    }
    return chart ? (
        <View style={[styles.skeleton, styles.skeletonChart]} />
    ) : (
        <View style={styles.skeletonNumber}>
            <View style={[styles.skeleton, styles.skeletonValue]} />
            <View style={[styles.skeleton, styles.skeletonSpark]} />
        </View>
    )
}

interface PinDelta {
    props: { delta: NonNullable<InsightSnapshot['delta']>; formatValue: (value: number) => string; basis: string }
    spoken: string
}

function pinDelta(snapshot: InsightSnapshot, formatValue: (value: number) => string): PinDelta | null {
    const { delta } = snapshot
    if (!delta) {
        return null
    }
    const basis = deltaBasisText(delta, snapshot.interval)
    return { props: { delta, formatValue, basis }, spoken: deltaSpoken(delta, formatValue, basis) }
}

/** The thin bar at the bottom of a Number or Chart pin while its request runs. */
function ProgressLine({ active }: { active: boolean }): ReactElement | null {
    const styles = useStyles()
    const reduceMotion = useReducedMotion()
    const position = useSharedValue(0)
    useEffect(() => {
        if (!active || reduceMotion) {
            cancelAnimation(position)
            position.value = 0
            return
        }
        position.value = 0
        position.value = withRepeat(withTiming(1, { duration: 1100, easing: Easing.inOut(Easing.ease) }), -1, false)
    }, [active, reduceMotion, position])
    const barStyle = useAnimatedStyle(() => ({ left: `${-40 + position.value * 140}%` }))
    if (!active) {
        return null
    }
    return (
        <View style={styles.progress} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            <Animated.View style={[styles.progressBar, reduceMotion ? styles.progressStill : barStyle]} />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.option,
        overflow: 'hidden',
    },
    head: {
        height: HEAD_HEIGHT,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: 12,
    },
    iconTile: {
        width: 34,
        height: 34,
        borderRadius: radii.markLarge,
        backgroundColor: colors.sunken,
        alignItems: 'center',
        justifyContent: 'center',
    },
    headText: {
        flex: 1,
        minWidth: 0,
    },
    title: {
        ...type.rowTitle,
        color: colors.ink,
    },
    dimText: {
        color: colors.tertiary,
    },
    meta: {
        ...type.meta,
        color: colors.tertiary,
    },
    numberBody: {
        minHeight: NUMBER_BODY_HEIGHT,
        flexDirection: 'row',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        gap: 14,
        paddingHorizontal: 14,
        paddingBottom: 14,
    },
    valueColumn: {
        flexShrink: 1,
        gap: 4,
        alignItems: 'flex-start',
    },
    bigValue: {
        fontSize: 32,
        fontWeight: '700',
        letterSpacing: -0.6,
        lineHeight: 35,
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    deltaRow: {
        height: 22,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    valueRow: {
        height: VALUE_ROW_HEIGHT,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingHorizontal: 14,
        paddingBottom: 6,
    },
    chartValue: {
        fontSize: 24,
        fontWeight: '700',
        letterSpacing: -0.4,
        lineHeight: 27,
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    chartArea: {
        height: COMPACT_CHART_HEIGHT + CHART_BOTTOM,
        paddingHorizontal: 14,
        paddingBottom: CHART_BOTTOM,
    },
    footer: {
        paddingHorizontal: 14,
        paddingBottom: 8,
    },
    legend: {
        paddingHorizontal: 14,
        paddingBottom: 12,
    },
    stale: {
        opacity: 0.45,
    },
    stateRow: {
        flex: 1,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    stateGrow: {
        flex: 1,
    },
    stateText: {
        ...type.meta,
        color: colors.secondary,
        alignSelf: 'center',
    },
    textButton: {
        minHeight: 32,
        justifyContent: 'center',
        paddingHorizontal: 4,
    },
    textAction: {
        ...type.buttonSmall,
        color: colors.blue,
    },
    skeleton: {
        backgroundColor: colors.sunken,
        borderRadius: 8,
    },
    skeletonNumber: {
        flex: 1,
        flexDirection: 'row',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
    },
    skeletonValue: {
        width: 96,
        height: 26,
    },
    skeletonSpark: {
        width: 120,
        height: 36,
    },
    skeletonChart: {
        flex: 1,
    },
    progress: {
        position: 'absolute',
        left: 14,
        right: 14,
        bottom: 0,
        height: 2,
        borderRadius: 1,
        overflow: 'hidden',
        backgroundColor: colors.sunken,
    },
    progressBar: {
        position: 'absolute',
        top: 0,
        bottom: 0,
        width: '40%',
        borderRadius: 1,
        backgroundColor: colors.blue,
    },
    progressStill: {
        left: 0,
    },
}))
