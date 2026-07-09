import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { COMPARE_CURRENT_BORDER, COMPARE_PREVIOUS_BORDER } from '../../SparklineCompareOverlay'
import { type OverlayWindow, TIME_COMPARE_PRESET_DEFS, tracingFiltersLogic } from '../../tracingFiltersLogic'

// Windows are absolute ms; the tracing scene displays everything in UTC (see the sparkline's
// displayTimezone), so the pills must match or the ranges look shifted vs the chart.
function formatComparisonWindow(window: OverlayWindow): string {
    const start = dayjs(window.startMs).utc()
    const end = dayjs(window.endMs).utc()
    const endFormat = start.isSame(end, 'day') ? 'HH:mm' : 'MMM D, HH:mm'
    return `${start.format('MMM D, HH:mm')} – ${end.format(endFormat)} UTC`
}

function ComparisonPill({ color, label, detail }: { color: string; label: string; detail: string }): JSX.Element {
    return (
        <LemonTag icon={<span className="inline-block size-2 rounded-full" style={{ backgroundColor: color }} />}>
            <span className="font-semibold">{label}</span>
            <span className="text-muted font-normal">{detail}</span>
        </LemonTag>
    )
}

/**
 * Spells out what an active comparison is comparing — side A (current) vs side B (baseline) —
 * so the compare table's deltas are never ambiguous. Rendered above the results while a
 * comparison is active.
 */
export function ComparisonBar(): JSX.Element | null {
    const { comparison, currentWindowMs, previousWindowMs } = useValues(tracingFiltersLogic)
    const { setComparison } = useActions(tracingFiltersLogic)

    if (comparison?.mode !== 'time') {
        return null
    }

    const presetDef = TIME_COMPARE_PRESET_DEFS[comparison.preset]

    return (
        <div className="flex items-center gap-2 flex-wrap" data-attr="tracing-comparison-bar">
            <ComparisonPill
                color={COMPARE_CURRENT_BORDER}
                label="Current"
                detail={formatComparisonWindow(currentWindowMs)}
            />
            <span className="text-muted text-xs">vs</span>
            <ComparisonPill
                color={COMPARE_PREVIOUS_BORDER}
                label="Baseline"
                detail={`${formatComparisonWindow(previousWindowMs)} (${presetDef.baselineLabel})`}
            />
            {comparison.preset === 'custom' && (
                <span className="text-muted text-xs">Drag the windows on the chart to reposition or resize</span>
            )}
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                onClick={() => setComparison(null)}
                tooltip="Exit comparison"
                aria-label="Exit comparison"
                data-attr="tracing-comparison-exit"
                className="ml-auto"
            />
        </div>
    )
}
