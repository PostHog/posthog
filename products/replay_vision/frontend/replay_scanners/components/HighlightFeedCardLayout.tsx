import { forwardRef } from 'react'

import { IconFlag } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface HighlightFeedCardLayoutProps {
    scanner: React.ReactNode
    meta: React.ReactNode
    action?: React.ReactNode
    title: string
    titlePrefix?: React.ReactNode
    /** Filler picks say nothing about the session, so their title reads quieter. */
    titleMuted?: boolean
    /** Stretched over the whole card, so a click anywhere opens it. */
    titleLink?: { to: string; onClick?: () => void }
    why: string
    poster: React.ReactNode
    footer: React.ReactNode
    className?: string
    'data-attr'?: string
}

export const HighlightFeedCardLayout = forwardRef<HTMLElement, HighlightFeedCardLayoutProps>(
    function HighlightFeedCardLayout(
        {
            scanner,
            meta,
            action,
            title,
            titlePrefix,
            titleMuted = false,
            titleLink,
            why,
            poster,
            footer,
            className,
            'data-attr': dataAttr,
        },
        ref
    ): JSX.Element {
        const heading = (
            <h3
                // Two lines are always reserved, so cards in one grid row keep their posters level.
                className={cn(
                    'm-0 min-h-[2lh] text-base line-clamp-2 wrap-anywhere',
                    titleLink && 'group-hover:text-accent',
                    titleMuted ? 'font-medium text-secondary' : 'font-semibold'
                )}
                title={title}
            >
                {titlePrefix}
                {title}
            </h3>
        )
        return (
            <article
                ref={ref}
                className={cn(
                    'group relative flex min-w-0 flex-col gap-3 rounded-lg border bg-surface-primary p-4',
                    titleLink && 'hover:border-accent focus-within:border-accent',
                    className
                )}
                data-attr={dataAttr}
            >
                <header className="flex min-w-0 items-center gap-2">
                    <div className="flex min-w-0">{scanner}</div>
                    <span className="text-xs text-muted" aria-hidden>
                        ·
                    </span>
                    {/* The person and age keep up to 45% of the line, so a long email is cut before the scanner name. */}
                    <div className="min-w-0 max-w-[45%] shrink-0">{meta}</div>
                    {action && <div className="relative z-10 ml-auto shrink-0">{action}</div>}
                </header>
                <div className="flex min-w-0 flex-col gap-1">
                    {titleLink ? (
                        <Link
                            to={titleLink.to}
                            onClick={titleLink.onClick}
                            className="text-default after:absolute after:inset-0 after:content-['']"
                            data-attr="vision-highlight-feed-row-open"
                        >
                            {heading}
                        </Link>
                    ) : (
                        heading
                    )}
                    <p
                        className="m-0 flex items-start gap-1.5 text-sm text-secondary"
                        data-attr="vision-highlight-feed-why"
                    >
                        <Tooltip title="Why this recording">
                            <span className="mt-0.5 flex shrink-0">
                                <IconFlag className="text-accent" aria-hidden />
                            </span>
                        </Tooltip>
                        <span className="min-w-0 truncate" title={why}>
                            <span className="sr-only">Why this recording: </span>
                            {why}
                        </span>
                    </p>
                </div>
                {/* Clicks pass through the poster to the card's link, which sits beneath it. */}
                <div className="pointer-events-none relative overflow-hidden rounded-md border bg-surface-primary">
                    {poster}
                </div>
                <footer className="flex items-center gap-2">{footer}</footer>
            </article>
        )
    }
)
