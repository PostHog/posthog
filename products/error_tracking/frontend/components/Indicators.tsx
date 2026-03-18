import clsx from 'clsx'
import React from 'react'

import { LemonBadge, Tooltip, TooltipProps } from '@posthog/lemon-ui'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

export type IssueStatus = ErrorTrackingIssue['status']

export type Intent = 'data' | 'primary' | 'success' | 'warning' | 'danger' | 'muted' | undefined

const sizeVariants = {
    xsmall: 'gap-1 text-xs',
    small: 'gap-2 text-sm',
    medium: 'gap-3 text-base',
    large: 'gap-3 text-lg',
}

interface LabelIndicatorProps {
    intent: Intent
    label: string
    size: 'xsmall' | 'small' | 'medium' | 'large'
    tooltip?: string
    tooltipPlacement?: TooltipProps['placement']
    className?: string
}

export const LabelIndicator = React.forwardRef<HTMLDivElement, LabelIndicatorProps>(function LabelIndicator(
    { intent, label, size, tooltip, tooltipPlacement, className },
    ref
): JSX.Element {
    return (
        <Tooltip title={tooltip} placement={tooltipPlacement}>
            <div ref={ref} className={clsx('flex items-center cursor-help', className, sizeVariants[size])}>
                <LemonBadge status={intent} size="small" />
                <div>{label}</div>
            </div>
        </Tooltip>
    )
})

const STATUS_LABEL: Record<ErrorTrackingIssue['status'], string> = {
    active: 'Active',
    archived: 'Archived',
    resolved: 'Resolved',
    pending_release: 'Pending release',
    suppressed: 'Suppressed',
}

const STATUS_INTENT: Record<ErrorTrackingIssue['status'], Intent> = {
    active: 'warning',
    archived: 'muted',
    resolved: 'success',
    pending_release: 'muted',
    suppressed: 'danger',
}

export const STATUS_INTENT_LABEL: Record<ErrorTrackingIssue['status'], string> = {
    active: 'Mark issue as active again',
    suppressed: 'Suppress issue (new occurrences will be ignored)',
    archived: 'Archive issue',
    pending_release: 'Mark issue as resolved in next version (new occurrences will re-activate it)',
    resolved: 'Mark issue as resolved (new occurrences will re-activate it)',
}

const STATUS_TOOLTIP: Record<ErrorTrackingIssue['status'], string | undefined> = {
    suppressed: 'New occurrences of this issue are ignored',
    active: 'Ongoing issue',
    archived: undefined,
    resolved: 'Will become active again on next occurrence',
    pending_release: undefined,
}

interface StatusIndicatorProps {
    status: IssueStatus
    intent?: boolean
    size?: 'xsmall' | 'small' | 'medium' | 'large'
    /** Whether to show a tooltip explaining each status. If just `true`, tooltip placement defaults to `top`. */
    withTooltip?: boolean | TooltipProps['placement']
    className?: string
}

export const StatusIndicator = React.forwardRef<HTMLDivElement, StatusIndicatorProps>(function StatusIndicator(
    { status, size = 'small', intent = false, className, withTooltip },
    ref
): JSX.Element {
    return (
        <LabelIndicator
            intent={STATUS_INTENT[status]}
            size={size}
            label={intent ? STATUS_INTENT_LABEL[status] : STATUS_LABEL[status]}
            tooltip={withTooltip ? STATUS_TOOLTIP[status] : undefined}
            tooltipPlacement={withTooltip ? (typeof withTooltip === 'string' ? withTooltip : 'top') : undefined}
            className={className}
            ref={ref}
        />
    )
})
