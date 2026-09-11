import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { runStreamLogic } from '../../logics/runStreamLogic'

/**
 * Context-window fill for the composer footer, next to the model picker: "Context 66%", turning to the
 * warning color at 80% and the danger color at 95%. The exact token counts and the run cost live in the
 * tooltip. Hidden until the run reports usage.
 */
export function ContextUsageChip(): JSX.Element | null {
    const { contextUsage } = useValues(runStreamLogic)
    const used = contextUsage?.used
    const size = contextUsage?.size
    if (typeof used !== 'number' || typeof size !== 'number' || size <= 0) {
        return null
    }
    const percentage = Math.min(100, Math.round((used / size) * 100))
    const tone = percentage >= 95 ? 'text-danger' : percentage >= 80 ? 'text-warning' : 'text-muted'
    const cost = typeof contextUsage?.cost === 'number' ? ` · $${contextUsage.cost.toFixed(2)}` : ''
    return (
        <Tooltip title={`${humanFriendlyNumber(used)} of ${humanFriendlyNumber(size)} tokens${cost}`}>
            <span className={`text-xs tabular-nums whitespace-nowrap px-1 ${tone}`} data-attr="composer-context-usage">
                Context {percentage}%
            </span>
        </Tooltip>
    )
}
