import posthog from 'posthog-js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { LemonInput, SpinnerOverlay } from '@posthog/lemon-ui'
import {
    FlameGraph,
    type FlameGraphConfig,
    type FlameHit,
    type FlameTooltipContext,
    TooltipFooter,
    TooltipSurface,
} from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar, getSeriesColor } from 'lib/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SpanTreeNode } from '~/queries/schema/schema-general'

import { CHANGE_THRESHOLD, MIN_BASELINE_COUNT } from './compareUtils'
import type { TraceViewSurface } from './components/TraceView/traceViewLogic'
import { findFlamePath, type FlameTreeNode } from './flameTree'
import {
    buildTree,
    flameIdOf,
    nodeKey,
    toFlameNodes,
    type TraceFlameMeta,
    type TraceFlameSizeBy,
} from './traceFlameTree'
import { formatDuration } from './TraceWaterfallView'

/** Where the flame sits. Pinned: sent as the `surface` property of analytics events, so keep the values stable. */
export type TraceFlameSurface = TraceViewSurface | 'compare_modal'

function focusDepth(focused: FlameHit<TraceFlameMeta> | null): number {
    if (!focused) {
        return 0
    }
    return focused.kind === 'node' ? focused.node.depth + 1 : (focused.bundle.parent?.depth ?? -1) + 2
}

interface DeltaPctProps {
    current: number | null | undefined
    previous: number | null | undefined
    /** When true, increases are bad (red); decreases good (green). For latency/errors. */
    higherIsWorse?: boolean
}

function DeltaPct({ current, previous, higherIsWorse }: DeltaPctProps): JSX.Element | null {
    if (current === null || current === undefined || previous === null || previous === undefined) {
        return null
    }
    if (previous === 0 && current === 0) {
        return null
    }
    if (previous === 0) {
        // Can't compute a percentage from a zero baseline — surface it qualitatively.
        return <span className="text-success ml-1">(new)</span>
    }
    const diff = current - previous
    if (diff === 0) {
        return null
    }
    const pct = (diff / previous) * 100
    const sign = diff > 0 ? '+' : ''
    const worse = higherIsWorse ? diff > 0 : diff < 0
    const color = higherIsWorse === undefined ? 'text-muted' : worse ? 'text-danger' : 'text-success'
    return (
        <span className={`${color} ml-1`}>
            ({sign}
            {pct.toFixed(1)}%)
        </span>
    )
}

const fmtCount = (n: SpanTreeNode | null): string => (n ? humanFriendlyNumber(n.count) : '—')
const fmtDur = (v: number | undefined): string => (v === undefined ? '—' : formatDuration(v))

function DurationRow({
    label,
    field,
    current,
    previous,
}: {
    label: string
    field: 'p50_duration_nano' | 'p95_duration_nano' | 'p99_duration_nano' | 'total_duration_nano'
    current: SpanTreeNode | null
    previous: SpanTreeNode | null
}): JSX.Element {
    return (
        <div>
            {label}: {fmtDur(current?.[field])}
            <DeltaPct current={current?.[field]} previous={previous?.[field]} higherIsWorse />
            {previous ? ` (prev ${fmtDur(previous[field])})` : ''}
        </div>
    )
}

function SpanFlameTooltip({
    ctx,
    sizeBy,
}: {
    ctx: FlameTooltipContext<TraceFlameMeta>
    sizeBy: TraceFlameSizeBy
}): JSX.Element {
    const footer = ctx.canFocus ? <TooltipFooter>Click to zoom in</TooltipFooter> : null
    if (ctx.hit.kind === 'bundle') {
        const { bundle } = ctx.hit
        return (
            <TooltipSurface>
                <strong>
                    {bundle.count} small spans{bundle.parent ? ` in ${bundle.parent.name}` : ''}
                </strong>
                <div>
                    {sizeBy === 'total' ? 'total' : 'p50 sum'}: {formatDuration(bundle.value)}
                </div>
                {bundle.descendantCount > bundle.count ? (
                    <div>{bundle.descendantCount - bundle.count} nested spans</div>
                ) : null}
                {footer}
            </TooltipSurface>
        )
    }
    const { node } = ctx.hit
    const current = node.meta?.current ?? null
    const previous = node.meta?.previous ?? null
    return (
        <TooltipSurface>
            <div className="font-semibold break-all">{node.name}</div>
            <div className="opacity-70 mb-1">{node.meta?.serviceName}</div>
            <div>
                count: {fmtCount(current)}
                <DeltaPct current={current?.count} previous={previous?.count} />
                {previous ? ` (prev ${fmtCount(previous)})` : ''}
            </div>
            <DurationRow label="p50" field="p50_duration_nano" current={current} previous={previous} />
            <DurationRow label="p95" field="p95_duration_nano" current={current} previous={previous} />
            <DurationRow label="p99" field="p99_duration_nano" current={current} previous={previous} />
            <DurationRow label="total" field="total_duration_nano" current={current} previous={previous} />
            {current && current.error_count > 0 ? (
                <div>
                    errors: {humanFriendlyNumber(current.error_count)}
                    <DeltaPct current={current.error_count} previous={previous?.error_count} higherIsWorse />
                </div>
            ) : null}
            {footer}
        </TooltipSurface>
    )
}

interface TraceCompareFlameProps {
    /**
     * A tree to draw instead of the one built from `current` and `previous`. A single trace passes the tree of its
     * spans, which keeps an operation's calls apart under each caller. A given tree draws without diff colors,
     * colors bars by service and labels a bar with its span count.
     */
    tree?: FlameTreeNode
    current: SpanTreeNode[]
    previous: SpanTreeNode[] | null
    loading: boolean
    /** Span name the modal was opened for — the flame initially focuses on this node. */
    initialSpanName?: string | null
    /**
     * The `compareRowKey` of the operation to focus first. It takes the place of `initialSpanName`, because two services
     * can each run an operation of the same name.
     */
    initialFocusKey?: string | null
    /** Which metric sets each bar's width. 'p50' is the per-call cost (the compare view); 'total' is wall-clock time summed over the calls (a single trace). */
    sizeBy?: TraceFlameSizeBy
    /** Colors a single trace's bars by service. Pass the waterfall's map so both views use the same color for a service. */
    serviceColorMap?: Map<string, number>
    /** Where the flame sits, for analytics. */
    surface: TraceFlameSurface
}

export function TraceCompareFlame({
    tree: givenTree,
    current,
    previous,
    loading,
    initialSpanName,
    initialFocusKey,
    sizeBy = 'p50',
    serviceColorMap,
    surface,
}: TraceCompareFlameProps): JSX.Element {
    const theme = useChartTheme()
    const [search, setSearch] = useState('')
    const tree = useMemo(() => givenTree ?? buildTree(current, previous), [givenTree, current, previous])
    // The compare modal compares even while `previous` is null, before its first fetch ends.
    const hasBaseline = givenTree === undefined
    const errorColor = useMemo(
        () => (hasBaseline ? undefined : getColorVar('danger')),
        // `theme` changes with the light and dark mode, which changes the color.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [hasBaseline, theme]
    )
    const data = useMemo(
        () => toFlameNodes(tree, { sizeBy, hasBaseline, errorColor }),
        [tree, sizeBy, hasBaseline, errorColor]
    )
    const config = useMemo((): FlameGraphConfig => {
        const groupColors = serviceColorMap
            ? Object.fromEntries(Array.from(serviceColorMap, ([service, index]) => [service, getSeriesColor(index)]))
            : undefined
        return {
            diff: { threshold: CHANGE_THRESHOLD, minCount: MIN_BASELINE_COUNT },
            valueFormatter: formatDuration,
            maxHeight: 640,
            groupColors,
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [serviceColorMap, theme])

    const initialFocus = useMemo(() => {
        const matches = initialFocusKey
            ? (node: FlameTreeNode): boolean => nodeKey(node) === initialFocusKey
            : initialSpanName
              ? (node: FlameTreeNode): boolean => node.name === initialSpanName
              : null
        const path = matches ? findFlamePath(tree, matches) : null
        return path ? { id: flameIdOf(path), depth: path.length } : null
    }, [tree, initialSpanName, initialFocusKey])
    // The chart reads its focus on mount only. A highlight that clears on the same tree keeps the drill-down,
    // because the trace view clears it on an inspector tab switch.
    const [mounted, setMounted] = useState({ tree, focus: initialFocus, version: 0 })
    if (mounted.tree !== tree || (initialFocus !== null && initialFocus.id !== mounted.focus?.id)) {
        setMounted({ tree, focus: initialFocus, version: mounted.version + 1 })
    }
    const depthRef = useRef(0)
    useEffect(() => {
        depthRef.current = mounted.focus?.depth ?? 0
    }, [mounted])

    const onFocusChange = useCallback(
        (focused: FlameHit<TraceFlameMeta> | null): void => {
            const depth = focusDepth(focused)
            if (depth !== depthRef.current) {
                // pinned: analytics event and property names, so renaming them breaks the insights built on them
                posthog.capture('tracing trace call tree focused', {
                    direction: depth > depthRef.current ? 'in' : 'out',
                    depth,
                    surface,
                })
            }
            depthRef.current = depth
        },
        [surface]
    )
    const renderTooltip = useCallback(
        (ctx: FlameTooltipContext<TraceFlameMeta>) => <SpanFlameTooltip ctx={ctx} sizeBy={sizeBy} />,
        [sizeBy]
    )

    if (loading) {
        return (
            <div className="relative min-h-32">
                <SpinnerOverlay />
            </div>
        )
    }

    if (tree.children.length === 0) {
        return <div className="text-muted text-center py-8">No spans found in the call tree for this row.</div>
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonInput
                type="search"
                size="small"
                className="max-w-80"
                placeholder="Search spans"
                value={search}
                onChange={setSearch}
            />
            <FlameGraph<TraceFlameMeta>
                key={mounted.version}
                data={data}
                theme={theme}
                config={config}
                search={search}
                defaultFocusedId={mounted.focus?.id}
                tooltip={renderTooltip}
                onFocusChange={onFocusChange}
                dataAttr="trace-compare-flame"
            />
        </div>
    )
}
