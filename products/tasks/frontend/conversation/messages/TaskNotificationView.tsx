import { JSX } from 'react'

import { IconCheckCircle, IconWarning, IconX, type Icon } from '../primitives/icons'

interface TaskNotificationViewProps {
    status: 'completed' | 'failed' | 'stopped'
    summary: string
}

interface StatusConfig {
    icon: Icon
    iconClassName: string
    label: string
    borderClassName: string
}

const STATUS_CONFIG: Record<TaskNotificationViewProps['status'], StatusConfig> = {
    completed: {
        icon: IconCheckCircle,
        iconClassName: 'text-success',
        label: 'Task completed',
        borderClassName: 'border-success',
    },
    failed: {
        icon: IconX,
        iconClassName: 'text-danger',
        label: 'Task failed',
        borderClassName: 'border-danger',
    },
    stopped: {
        icon: IconWarning,
        iconClassName: 'text-warning',
        label: 'Task stopped',
        borderClassName: 'border-warning',
    },
}

export function TaskNotificationView({ status, summary }: TaskNotificationViewProps): JSX.Element {
    const config = STATUS_CONFIG[status]
    const StatusIcon = config.icon

    return (
        <div className={`my-1 border-l-2 py-1 pl-3 ${config.borderClassName}`}>
            <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                    <StatusIcon className={config.iconClassName} style={{ fontSize: 14 }} />
                    <span className="font-medium text-[13px] text-default">{config.label}</span>
                </div>
                {summary && <span className="text-[13px] text-muted">{summary}</span>}
            </div>
        </div>
    )
}
