import type { ReactNode } from 'react'

import { ChatMarker, ChatMarkerContent, ChatMarkerIcon, Spinner, cn } from '@posthog/quill-primitives'

/**
 * The row chrome every quill thread row shares. Quill's interactive row bleeds its hit area past the
 * text column, fills on hover and draws an outset focus ring; a transcript is mostly these rows, so they
 * stay flush with the column and muted until hovered or opened.
 */
const QUILL_THREAD_ROW_CLASS = cn(
    'mx-0 px-0 opacity-60 hover:bg-transparent focus-visible:bg-transparent',
    'hover:opacity-100 data-panel-open:bg-transparent data-panel-open:opacity-100',
    '[&_[data-slot=marker-panel]]:pt-2 [&_[data-slot=marker-panel]]:pb-1',
    // Quill parks the chevron at the row's far end, which strands it from the text it opens.
    '[&>svg:last-child]:ms-0',
    'focus-visible:shadow-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring'
)

export interface ThreadMarkerProps {
    icon?: ReactNode
    running?: boolean
    spinner?: boolean
    failed?: boolean
    body?: ReactNode
    open?: boolean
    onOpenChange?: (open: boolean) => void
    className?: string
    children: ReactNode
}

export function ThreadMarker({
    icon,
    running = false,
    spinner = false,
    failed = false,
    body,
    open,
    onOpenChange,
    className,
    children,
}: ThreadMarkerProps): JSX.Element {
    return (
        <ChatMarker
            status={failed ? 'error' : running ? 'running' : undefined}
            body={body}
            open={open}
            onOpenChange={onOpenChange}
            className={cn(QUILL_THREAD_ROW_CLASS, (failed || running) && 'opacity-100', className)}
        >
            {(icon || (running && spinner)) && (
                <ChatMarkerIcon>{running && spinner ? <Spinner /> : icon}</ChatMarkerIcon>
            )}
            <ChatMarkerContent className="flex min-w-0 flex-nowrap items-center gap-1.5 overflow-hidden">
                {children}
            </ChatMarkerContent>
        </ChatMarker>
    )
}
