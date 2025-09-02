import { useValues } from 'kea'

import { IconCheck, IconFilter, IconX } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber } from 'lib/utils'

import { HogFlowEditorActionMetrics, hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { HogFlowAction } from '../../types'

export function StepViewMetrics({ action }: { action: HogFlowAction }): JSX.Element {
    const { actionMetricsById, actionMetricsByIdLoading } = useValues(hogFlowEditorLogic)

    const metrics: HogFlowEditorActionMetrics = actionMetricsById?.[action.id] ?? {
        actionId: action.id,
        succeeded: 0,
        failed: 0,
        filtered: 0,
    }

    if (actionMetricsByIdLoading) {
        return (
            <div className="flex items-center gap-1 h-2 px-1">
                <LemonSkeleton className="w-full h-[6px]" />
                <LemonSkeleton className="w-full h-[6px]" />
                <LemonSkeleton className="w-full h-[6px]" />
            </div>
        )
    }

    return (
        <div
            className="flex flex-row items-center font-mono"
            style={{
                fontSize: 6,
            }}
        >
            <Tooltip title="Successful runs of this action">
                <div className="flex-1 px-1 text-success">
                    <IconCheck /> {humanFriendlyLargeNumber(metrics.succeeded)}
                </div>
            </Tooltip>

            <Tooltip title="Failed runs of this action">
                <div className="flex-1 px-1 text-error">
                    <IconX /> {humanFriendlyLargeNumber(metrics.failed)}
                </div>
            </Tooltip>
            <Tooltip title="Filtered runs of this action">
                <div className="flex-1 px-1 text-muted">
                    <IconFilter /> {humanFriendlyLargeNumber(metrics.filtered)}
                </div>
            </Tooltip>
        </div>
    )
}
