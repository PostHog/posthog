import { useValues } from 'kea'

import { IconCheck, IconFilter, IconX } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { HogFlowEditorActionMetrics, hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { HogFlowAction } from '../../types'

export function StepViewMetrics({
    action,
    layout = 'node',
}: {
    action: HogFlowAction
    layout?: 'node' | 'list'
}): JSX.Element {
    const { actionMetricsById, actionMetricsByIdLoading } = useValues(hogFlowEditorLogic)

    const metrics: HogFlowEditorActionMetrics = actionMetricsById?.[action.id] ?? {
        actionId: action.id,
        succeeded: 0,
        failed: 0,
        filtered: 0,
    }

    if (actionMetricsByIdLoading) {
        return (
            <div
                className={
                    layout === 'list'
                        ? 'ml-auto flex h-7 w-32 shrink-0 items-center gap-2 self-center rounded border bg-fill-button-tertiary px-2'
                        : 'flex h-2 items-center gap-1 px-1'
                }
            >
                <LemonSkeleton className="w-full h-[6px]" />
                <LemonSkeleton className="w-full h-[6px]" />
                <LemonSkeleton className="w-full h-[6px]" />
            </div>
        )
    }

    return (
        <div
            className={
                layout === 'list'
                    ? 'ml-auto flex shrink-0 flex-row items-center gap-3 self-center rounded border bg-fill-button-tertiary px-2 py-1 text-xs font-mono'
                    : 'flex flex-row items-center text-[6px] font-mono'
            }
        >
            <Tooltip title="Successful runs of this action">
                <div
                    className={layout === 'list' ? 'flex items-center gap-1 text-success' : 'flex-1 px-1 text-success'}
                >
                    <IconCheck /> {humanFriendlyLargeNumber(metrics.succeeded)}
                </div>
            </Tooltip>

            <Tooltip title="Failed runs of this action">
                <div className={layout === 'list' ? 'flex items-center gap-1 text-error' : 'flex-1 px-1 text-error'}>
                    <IconX /> {humanFriendlyLargeNumber(metrics.failed)}
                </div>
            </Tooltip>
            <Tooltip title="Filtered runs of this action">
                <div className={layout === 'list' ? 'flex items-center gap-1 text-muted' : 'flex-1 px-1 text-muted'}>
                    <IconFilter /> {humanFriendlyLargeNumber(metrics.filtered)}
                </div>
            </Tooltip>
        </div>
    )
}
