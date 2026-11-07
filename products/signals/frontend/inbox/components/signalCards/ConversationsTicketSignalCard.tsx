import { useState } from 'react'

import { IconChevronRight, IconImage } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { ConversationsTicketImageApi } from 'products/signals/frontend/generated/api.schemas'
import { conversationsTicketUrl } from 'products/signals/frontend/inbox/utils/signalLinks'

import { IMAGE_PREVIEW_COUNT, ticketExtra, ticketImageLink } from './signalCardParsing'
import { SignalCardShell } from './SignalCardShell'
import type { SignalCardProps } from './types'

/**
 * One attachment thumbnail that opens the full image. Only an image PostHog serves loads inline: the
 * URL comes from ticket rich content, which is not origin-validated, and an inline `<img>` makes every
 * viewer's browser fetch it on render. Any other host is a click-to-open tile that loads nothing.
 * Drops out when the image can no longer be fetched.
 */
function TicketImageThumbnail({ image }: { image: ConversationsTicketImageApi }): JSX.Element | null {
    const [failed, setFailed] = useState(false)
    const link = ticketImageLink(image)
    if (failed || !link) {
        return null
    }
    return (
        <li>
            <Link
                to={link.href}
                target="_blank"
                className="flex items-center justify-center size-16 rounded border overflow-hidden bg-surface-secondary"
                title={link.title}
                aria-label={link.trusted ? undefined : link.label}
            >
                {link.trusted ? (
                    <img
                        src={link.href}
                        alt={link.label}
                        className="size-full object-cover"
                        loading="lazy"
                        onError={() => setFailed(true)}
                    />
                ) : (
                    <IconImage className="text-xl text-secondary" />
                )}
            </Link>
        </li>
    )
}

export function ConversationsTicketSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = ticketExtra(signal.extra)
    const images = Array.isArray(extra.images) ? extra.images : []
    const ticketUrl = conversationsTicketUrl(signal)

    return (
        <SignalCardShell signal={signal} label={extra.email_subject ?? undefined}>
            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}
            {images.length > 0 && (
                <ul className="flex flex-wrap items-center gap-1.5 mb-2">
                    {images.slice(0, IMAGE_PREVIEW_COUNT).map((image, index) => (
                        <TicketImageThumbnail key={`${image.url}-${index}`} image={image} />
                    ))}
                    {images.length > IMAGE_PREVIEW_COUNT && (
                        <li className="text-xs font-medium">
                            {ticketUrl ? (
                                <Link to={ticketUrl}>+{images.length - IMAGE_PREVIEW_COUNT} more</Link>
                            ) : (
                                <span className="text-tertiary">+{images.length - IMAGE_PREVIEW_COUNT} more</span>
                            )}
                        </li>
                    )}
                </ul>
            )}
            <div className="flex items-center gap-2 text-xs text-tertiary">
                {typeof extra.ticket_number === 'number' && (
                    <span className="font-mono font-medium">#{extra.ticket_number}</span>
                )}
                <span className="flex-1" />
                {ticketUrl ? (
                    <Link
                        to={ticketUrl}
                        className="flex items-center gap-1 text-xs font-medium"
                        data-attr="inbox-evidence-open-ticket"
                    >
                        Open ticket
                        <IconChevronRight />
                    </Link>
                ) : (
                    <span>Source ticket unavailable</span>
                )}
            </div>
        </SignalCardShell>
    )
}
