import { IconCheck, IconPause, IconRefresh, IconSend, IconWarning } from '@posthog/icons'

export function SendCalendarLegend(): JSX.Element {
    return (
        <div
            className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-secondary"
            data-attr="send-calendar-legend"
        >
            <span className="flex items-center gap-1">
                <span className="size-2 shrink-0 rounded-full bg-accent" />
                Broadcast
            </span>
            <span className="flex items-center gap-1">
                <span className="size-2 shrink-0 rounded-full bg-[var(--color-product-workflows-light)]" />
                Workflow
            </span>
            <span className="flex items-center gap-1">
                <IconRefresh className="shrink-0" />
                Repeats
            </span>
            <span className="flex items-center gap-1">
                <IconPause className="shrink-0" />
                Paused
            </span>
            <span className="flex items-center gap-1">
                <IconSend className="shrink-0" />
                Sending
            </span>
            <span className="flex items-center gap-1">
                <IconCheck className="shrink-0 text-success" />
                Sent
            </span>
            <span className="flex items-center gap-1">
                <IconWarning className="shrink-0 text-danger" />
                Failed
            </span>
        </div>
    )
}
