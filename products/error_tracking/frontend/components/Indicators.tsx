import clsx from 'clsx'
import React from 'react'

import { LemonBadge, Tooltip as LemonTooltip, TooltipProps } from '@posthog/lemon-ui'

import { Dot, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

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
        <LemonTooltip title={tooltip} placement={tooltipPlacement}>
            <div
                ref={ref}
                className={clsx('flex items-center', tooltip && 'cursor-help', className, sizeVariants[size])}
            >
                <LemonBadge status={intent} size="small" />
                <div>{label}</div>
            </div>
        </LemonTooltip>
    )
})

interface IssueStatusConfig {
    color: string
    intentLabel: string
    label: string
    tooltip?: string
}

export const ISSUE_STATUS_CONFIG: Record<IssueStatus, IssueStatusConfig> = {
    active: {
        color: '#f59e0b',
        intentLabel: 'Mark issue as active again',
        label: 'Active',
        tooltip: 'Ongoing issue',
    },
    archived: {
        color: '#6b7280',
        intentLabel: 'Archive issue',
        label: 'Archived',
    },
    pending_release: {
        color: '#3b82f6',
        intentLabel: 'Mark issue as resolved in next version (new occurrences will re-activate it)',
        label: 'Pending release',
    },
    resolved: {
        color: '#22c55e',
        intentLabel: 'Mark issue as resolved (new occurrences will re-activate it)',
        label: 'Resolved',
        tooltip: 'Will become active again on next occurrence',
    },
    suppressed: {
        color: '#ef4444',
        intentLabel: 'Suppress issue (new occurrences will be ignored)',
        label: 'Suppressed',
        tooltip: 'New occurrences of this issue are ignored',
    },
}

export const IssueStatusDot = ({ status, className }: { status: IssueStatus; className?: string }): JSX.Element => (
    <Dot
        className={clsx('!border-0 !p-0 [&_[data-slot=dot-inner]]:!bg-[var(--error-tracking-status-color)]', className)}
        style={{ '--error-tracking-status-color': ISSUE_STATUS_CONFIG[status].color } as React.CSSProperties}
    />
)

interface StatusIndicatorProps {
    status: IssueStatus
    intent?: boolean
    size?: 'xsmall' | 'small' | 'medium' | 'large'
    /** Whether to show a tooltip explaining each status. If just `true`, tooltip placement defaults to `top`. */
    withTooltip?: boolean | NonNullable<React.ComponentProps<typeof TooltipContent>['side']>
    className?: string
}

export const StatusIndicator = React.forwardRef<HTMLDivElement, StatusIndicatorProps>(function StatusIndicator(
    { status, size = 'small', intent = false, className, withTooltip },
    ref
): JSX.Element {
    const config = ISSUE_STATUS_CONFIG[status]
    const tooltip = withTooltip ? config.tooltip : undefined
    const content = (
        <div ref={ref} className={clsx('flex items-center', className, sizeVariants[size])}>
            <IssueStatusDot status={status} />
            <div>{intent ? config.intentLabel : config.label}</div>
        </div>
    )

    if (!tooltip) {
        return content
    }

    return (
        <Tooltip>
            <TooltipTrigger render={content} />
            <TooltipContent side={typeof withTooltip === 'string' ? withTooltip : 'top'}>{tooltip}</TooltipContent>
        </Tooltip>
    )
})
