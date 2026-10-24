import { useCallback, useMemo, useState } from 'react'

import { LemonInput, SpinnerOverlay } from '@posthog/lemon-ui'
import {
    FlameGraph,
    type FlameGraphConfig,
    type FlameTooltipContext,
    TooltipFooter,
    TooltipSurface,
} from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SpanTreeNode } from '~/queries/schema/schema-general'

import { CHANGE_THRESHOLD, MIN_BASELINE_COUNT } from './compareUtils'
import { buildTree, findFlameIdByName, toFlameNodes, type TraceFlameMeta } from './traceFlameTree'
import { formatDuration } from './TraceWaterfallView'

const FLAME_CONFIG: FlameGraphConfig = {
    diff: { threshold: CHANGE_THRESHOLD, minCount: MIN_BASELINE_COUNT },
    valueFormatter: formatDuration,
    maxHeight: 640,
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

function SpanFlameTooltip({ ctx }: { ctx: FlameTooltipContext<TraceFlameMeta> }): JSX.Element {
    const footer = ctx.canFocus ? <TooltipFooter>Click to zoom in</TooltipFooter> : null
    if (ctx.hit.kind === 'bundle') {
        const { bundle } = ctx.hit
        return (
            <TooltipSurface>
                <strong>
                    {bundle.descendantCount} small spans in {bundle.parent.name}
                </strong>
                <div>p50 sum: {formatDuration(bundle.value)}</div>
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
    current: SpanTreeNode[]
    previous: SpanTreeNode[] | null
    loading: boolean
    /** Span name the modal was opened for — the flame initially focuses on this node. */
    initialSpanName?: string | null
}

export function TraceCompareFlame({
    current,
    previous,
    loading,
    initialSpanName,
}: TraceCompareFlameProps): JSX.Element {
    const theme = useChartTheme()
    const [search, setSearch] = useState('')
    const tree = useMemo(() => buildTree(current, previous), [current, previous])
    const data = useMemo(() => toFlameNodes(tree, previous !== null), [tree, previous])
    const initialFocusId = useMemo(
        () => (initialSpanName ? findFlameIdByName(tree, initialSpanName) : null),
        [tree, initialSpanName]
    )
    const renderTooltip = useCallback((ctx: FlameTooltipContext<TraceFlameMeta>) => <SpanFlameTooltip ctx={ctx} />, [])

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
                data={data}
                theme={theme}
                config={FLAME_CONFIG}
                search={search}
                defaultFocusedId={initialFocusId}
                tooltip={renderTooltip}
                dataAttr="trace-compare-flame"
            />
        </div>
    )
}
