import type { ReactNode } from 'react'

import { ChatMarker, ChatMarkerContent, ChatMarkerIcon, Spinner, cn } from '@posthog/quill-primitives'

/**
 * The row chrome every quill thread row shares. Quill's interactive row bleeds its hit area past the
 * text column, fills on hover and draws an outset focus ring; a transcript is mostly these rows, so they
 * stay flush with the column. Rows read in the thread's text color, not quill's muted row color.
 */
const QUILL_THREAD_ROW_CLASS = cn(
    'mx-0 px-0 text-foreground hover:bg-transparent focus-visible:bg-transparent',
    'data-panel-open:bg-transparent',
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
            className={cn(
                QUILL_THREAD_ROW_CLASS,
                // A fainter base under the full-foreground sweep, so a live row reads as moving at a glance.
                running && '[--quill-shimmer-base:color-mix(in_oklab,var(--muted-foreground)_70%,transparent)]',
                className
            )}
        >
            {(icon || (running && spinner)) && (
                <ChatMarkerIcon className="flex items-center justify-center">
                    {running && spinner ? <Spinner /> : icon}
                </ChatMarkerIcon>
            )}
            <ChatMarkerContent className="flex min-w-0 flex-nowrap items-center gap-1.5 overflow-hidden">
                {children}
            </ChatMarkerContent>
        </ChatMarker>
    )
}
