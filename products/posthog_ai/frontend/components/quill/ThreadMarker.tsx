import type { ReactNode } from 'react'

import { ChatMarker, ChatMarkerContent, ChatMarkerIcon, Spinner, cn } from '@posthog/quill-primitives'

/**
 * The row chrome every quill thread row shares, matching PostHog Desktop's tool rows. Quill's interactive row
 * bleeds its hit area past the text column, fills on hover and draws an outset focus ring; a transcript is
 * mostly these rows, so they stay flush with the column and at half opacity next to the prose.
 */
const QUILL_THREAD_ROW_CLASS = cn(
    'mx-0 px-0 opacity-50 hover:bg-transparent focus-visible:bg-transparent',
    '[&_[data-slot=marker-panel]]:pt-2 [&_[data-slot=marker-panel]]:pb-1',
    // Quill parks the chevron at the row's far end, which strands it from the text it opens.
    '[&>svg:last-child]:ms-0',
    'focus-visible:shadow-none focus-visible:ring-(--ring)/50 focus-visible:ring-2 focus-visible:ring-inset'
)

export interface ThreadMarkerProps {
    icon?: ReactNode
    running?: boolean
    /** Swaps the icon for a spinner while running. */
    spinner?: boolean
    /** Sweeps the text while running. A tool row turns this off and shows only its spinner. */
    shimmer?: boolean
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
    shimmer = true,
    failed = false,
    body,
    open,
    onOpenChange,
    className,
    children,
}: ThreadMarkerProps): JSX.Element {
    const opens = body != null && body !== false && body !== ''
    return (
        <ChatMarker
            status={failed ? 'error' : running && shimmer ? 'running' : undefined}
            body={body}
            open={open}
            onOpenChange={onOpenChange}
            className={cn(
                QUILL_THREAD_ROW_CLASS,
                opens && 'hover:opacity-100 data-panel-open:bg-transparent data-panel-open:opacity-100',
                // The title, argument and status label each set their own color, so the row's color loses to them.
                failed && 'opacity-100 text-(--destructive-foreground) [&_*]:text-(--destructive-foreground)',
                // A fainter base under the full-foreground sweep, so a live row reads as moving at a glance.
                running &&
                    shimmer &&
                    '[--quill-shimmer-base:color-mix(in_oklab,var(--muted-foreground)_70%,transparent)]',
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
