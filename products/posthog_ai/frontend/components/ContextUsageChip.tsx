import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { runStreamLogic } from '../logics/runStreamLogic'
import { taskComputeCostLogic } from '../logics/taskComputeCostLogic'
import type { ContextUsage } from '../types/streamTypes'

/**
 * Context-window fill and run cost as one line of text: "Context 66% · $12.79". The percentage turns
 * to the warning color at 80% and the danger color at 95%; the tooltip carries the exact token counts.
 * The cost is the model spend the run reports, plus the task's billed sandbox compute after each turn.
 * Hidden until the run reports usage or cost. Rendered in the runner's composer footer, the Max
 * sandbox panel, and the thread footer of composer-less live embeds.
 */
export function ContextUsageChip(): JSX.Element | null {
    const { contextUsage, bootstrappedTaskId, turnComplete } = useValues(runStreamLogic)
    return bootstrappedTaskId ? (
        <TaskContextUsageChip taskId={bootstrappedTaskId} contextUsage={contextUsage} turnComplete={turnComplete} />
    ) : (
        <ContextUsageLabel contextUsage={contextUsage} computeCostUsd={0} />
    )
}

function TaskContextUsageChip({
    taskId,
    contextUsage,
    turnComplete,
}: {
    taskId: string
    contextUsage: ContextUsage | null
    turnComplete: boolean
}): JSX.Element | null {
    const logic = taskComputeCostLogic({ taskId })
    const { computeCostUsd } = useValues(logic)
    const { loadComputeCost } = useActions(logic)
    useEffect(() => {
        if (turnComplete) {
            loadComputeCost()
        }
    }, [turnComplete, loadComputeCost])
    return <ContextUsageLabel contextUsage={contextUsage} computeCostUsd={computeCostUsd} />
}

function ContextUsageLabel({
    contextUsage,
    computeCostUsd,
}: {
    contextUsage: ContextUsage | null
    computeCostUsd: number
}): JSX.Element | null {
    const used = contextUsage?.used
    const size = contextUsage?.size
    const hasRing = typeof used === 'number' && typeof size === 'number' && size > 0
    const modelCost = typeof contextUsage?.cost === 'number' ? contextUsage.cost : null
    const cost = computeCostUsd > 0 ? (modelCost ?? 0) + computeCostUsd : modelCost
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
