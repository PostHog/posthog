import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { runStreamLogic } from '../logics/runStreamLogic'

/**
 * Context-window fill and run cost as one line of text: "Context 66% · $12.79". The percentage turns
 * to the warning color at 80% and the danger color at 95%; the tooltip carries the exact token counts.
 * Hidden until the run reports usage or cost. Rendered in the runner's composer footer, the Max
 * sandbox panel, and the thread footer of composer-less live embeds.
 */
export function ContextUsageChip(): JSX.Element | null {
    const { contextUsage } = useValues(runStreamLogic)
    const used = contextUsage?.used
    const size = contextUsage?.size
    const hasRing = typeof used === 'number' && typeof size === 'number' && size > 0
    const cost = typeof contextUsage?.cost === 'number' ? contextUsage.cost : null
    if (!hasRing && cost === null) {
        return null
    }
    const percentage = hasRing ? Math.min(100, Math.round((used / size) * 100)) : null
    const tone =
        percentage !== null && percentage >= 95
            ? 'text-danger'
            : percentage !== null && percentage >= 80
              ? 'text-warning'
              : 'text-muted'
    const parts = [
        percentage !== null ? `Context ${percentage}%` : null,
        cost !== null ? `$${cost.toFixed(2)}` : null,
    ].filter(Boolean)
    const label = (
        <span className={`text-xs tabular-nums whitespace-nowrap px-1 ${tone}`} data-attr="max-sandbox-context-usage">
            {parts.join(' · ')}
        </span>
    )
    return hasRing ? (
        <Tooltip title={`${humanFriendlyNumber(used)} of ${humanFriendlyNumber(size)} tokens`}>{label}</Tooltip>
    ) : (
        label
    )
}
