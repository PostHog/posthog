import { IconLive } from '@posthog/icons'
import type { LemonTagType } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { LogMessage } from '~/queries/schema/schema-general'

// Matches LogTag, so the mark reads in the same colour as the log's level tag.
export const LOG_MARK_TAG_TYPE: Record<LogMessage['severity_text'], LemonTagType> = {
    trace: 'muted',
    debug: 'muted',
    info: 'default',
    warn: 'warning',
    error: 'danger',
    fatal: 'danger',
}

const MARK_CLASS: Partial<Record<LemonTagType, string>> = {
    danger: 'bg-danger',
    warning: 'bg-warning',
    default: 'bg-secondary',
    muted: 'bg-muted',
}

// One mark across the strip, the span chip and the bar pin, so a person learns once which mark is their log.
export function TraceDialogLogMark({
    severity,
    className,
}: {
    severity: LogMessage['severity_text']
    className?: string
}): JSX.Element {
    return (
        <span
            className={cn(
                'inline-flex size-3.5 shrink-0 items-center justify-center rounded-sm text-[10px] text-white',
                MARK_CLASS[LOG_MARK_TAG_TYPE[severity]] ?? 'bg-muted',
                className
            )}
            aria-hidden
        >
            <IconLive />
        </span>
    )
}
