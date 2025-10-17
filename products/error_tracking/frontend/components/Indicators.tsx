import clsx from 'clsx'

import { LemonBadge, Tooltip } from '@posthog/lemon-ui'

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
    className?: string
}

export function LabelIndicator({ intent, label, size, tooltip, className }: LabelIndicatorProps): JSX.Element {
    return (
        <Tooltip title={tooltip} placement="right">
            <div className={clsx('flex items-center', className, sizeVariants[size])}>
                <LemonBadge status={intent} size="small" />
                <div>{label}</div>
            </div>
        </Tooltip>
    )
}

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

const STATUS_INTENT_LABEL: Record<ErrorTrackingIssue['status'], string> = {
    active: 'Reopen issue',
    suppressed: 'Suppress issue',
    archived: 'Archive issue',
    pending_release: 'Resolve in next version',
    resolved: 'Resolve issue',
}

const STATUS_TOOLTIP: Record<ErrorTrackingIssue['status'], string | undefined> = {
    suppressed: 'Stop capturing this issue',
    active: 'Ongoing issue',
    archived: undefined,
    resolved: 'Will become active again on next occurrence',
    pending_release: undefined,
}

interface StatusIndicatorProps {
    status: IssueStatus
    intent?: boolean
    size?: 'xsmall' | 'small' | 'medium' | 'large'
    withTooltip?: boolean
    className?: string
}

export function StatusIndicator({
    status,
    size = 'small',
    intent = false,
    className,
    withTooltip,
}: StatusIndicatorProps): JSX.Element {
    return (
        <LabelIndicator
            intent={STATUS_INTENT[status]}
            size={size}
            label={intent ? STATUS_INTENT_LABEL[status] : STATUS_LABEL[status]}
            tooltip={withTooltip ? STATUS_TOOLTIP[status] : undefined}
            className={className}
        />
    )
}
