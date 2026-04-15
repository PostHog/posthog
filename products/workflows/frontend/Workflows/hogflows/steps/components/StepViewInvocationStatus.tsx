import { useValues } from 'kea'

import { IconCheck, IconClock, IconFilter, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { InvocationNodeStatus } from '../../../invocationViewLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { HogFlowAction } from '../../types'

const STATUS_CONFIG: Record<InvocationNodeStatus, { icon: JSX.Element; label: string; className: string }> = {
    succeeded: { icon: <IconCheck />, label: 'Succeeded', className: 'text-success' },
    completed: { icon: <IconCheck />, label: 'Completed', className: 'text-success' },
    failed: { icon: <IconX />, label: 'Failed', className: 'text-danger' },
    filtered: { icon: <IconFilter />, label: 'Filtered', className: 'text-muted' },
    waiting: { icon: <IconClock />, label: 'Waiting', className: 'text-warning' },
    not_reached: { icon: <></>, label: '', className: 'text-muted' },
}

export function StepViewInvocationStatus({ action }: { action: HogFlowAction }): JSX.Element | null {
    const { invocationNodeStatuses } = useValues(hogFlowEditorLogic)

    const status: InvocationNodeStatus = (invocationNodeStatuses[action.id] as InvocationNodeStatus) ?? 'not_reached'

    if (status === 'not_reached') {
        return null
    }

    const config = STATUS_CONFIG[status]

    return (
        <Tooltip title={config.label}>
            <div
                className={`flex flex-row items-center gap-0.5 font-mono px-1 ${config.className}`}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ fontSize: 6 }}
            >
                {config.icon}
                <span>{config.label}</span>
            </div>
        </Tooltip>
    )
}
