import { Badge, Spinner, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { ReplayObservationApi } from '../generated/api.schemas'
import {
    failureKindDescription,
    ineligibleKindDescription,
    parseFailureReason,
    parseIneligibleReason,
} from '../replay_scanners/types'

function BadgeWithTooltip({
    tooltip,
    variant,
    className,
    children,
}: {
    tooltip: React.ReactNode
    variant: 'destructive' | 'default'
    className?: string
    children: string
}): JSX.Element {
    const badge = (
        <Badge variant={variant} className={className}>
            {children}
        </Badge>
    )
    if (!tooltip) {
        return badge
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="flex" />}>{badge}</TooltipTrigger>
            <TooltipContent className="max-w-72">{tooltip}</TooltipContent>
        </Tooltip>
    )
}

export function QuillObservationStatusTag({
    status,
    errorReason,
}: {
    status: ReplayObservationApi['status']
    // Required, not optional: an omitted reason silently drops the tooltip that explains a failed or ineligible status.
    errorReason: string | null
}): JSX.Element {
    if (status === 'succeeded') {
        return <Badge variant="success">Succeeded</Badge>
    }
    if (status === 'failed') {
        const parsed = errorReason ? parseFailureReason(errorReason) : null
        const tooltip = parsed ? (
            <span className="flex flex-col gap-1">
                <span>{parsed.label}</span>
                <span className="text-xs opacity-80">{failureKindDescription(parsed.kind)}</span>
            </span>
        ) : (
            errorReason || null
        )
        return (
            <BadgeWithTooltip tooltip={tooltip} variant="destructive">
                Failed
            </BadgeWithTooltip>
        )
    }
    if (status === 'ineligible') {
        // Muted, not destructive: the session was skipped at the gate, not a scanner failure.
        const parsed = errorReason ? parseIneligibleReason(errorReason) : null
        const tooltip = parsed ? (
            <span className="flex flex-col gap-1">
                <span>{ineligibleKindDescription(parsed.kind)}</span>
                {parsed.message && <span className="text-xs opacity-80">{parsed.message}</span>}
            </span>
        ) : (
            errorReason || null
        )
        return (
            <BadgeWithTooltip tooltip={tooltip} variant="default" className="opacity-70">
                Ineligible
            </BadgeWithTooltip>
        )
    }
    if (status === 'running') {
        return (
            <Badge variant="warning" className="gap-1">
                <Spinner /> Running
            </Badge>
        )
    }
    return <Badge>Pending</Badge>
}
