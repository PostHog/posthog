import { useState } from 'react'

import { IconChevronRight, IconImage } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { ConversationsTicketImageApi } from 'products/signals/frontend/generated/api.schemas'
import { conversationsTicketUrl } from 'products/signals/frontend/inbox/utils/signalLinks'

import { QuillSignalCardLink } from './QuillSignalCardLink'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'
import { IMAGE_PREVIEW_COUNT, ticketExtra, ticketImageLink } from './signalCardParsing'
import type { SignalCardProps } from './types'

/**
 * One attachment thumbnail that opens the full image. Only an image PostHog serves loads inline; any other
 * host is a click-to-open tile that loads nothing (see `ticketImageLink`). Drops out when the image can no
 * longer be fetched.
 */
function QuillTicketImageThumbnail({ image }: { image: ConversationsTicketImageApi }): JSX.Element | null {
    const [failed, setFailed] = useState(false)
    const link = ticketImageLink(image)
    if (failed || !link) {
        return null
    }
    return (
        <li>
            <LinkPrimitive
                to={link.href}
                target="_blank"
                className="flex size-16 items-center justify-center overflow-hidden rounded-md border border-border bg-muted text-muted-foreground hover:bg-fill-hover"
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
                    <IconImage className="text-xl" />
                )}
            </LinkPrimitive>
        </li>
    )
}

export function QuillConversationsTicketSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = ticketExtra(signal.extra)
    const images = Array.isArray(extra.images) ? extra.images : []
    const ticketUrl = conversationsTicketUrl(signal)
    const moreImagesLabel = `+${images.length - IMAGE_PREVIEW_COUNT} more`

    return (
        <QuillSignalCardShell signal={signal} label={extra.email_subject ?? undefined}>
            {signal.content && <QuillSignalCardMarkdown>{signal.content}</QuillSignalCardMarkdown>}
            {images.length > 0 && (
                <ul className="flex flex-wrap items-center gap-1.5">
                    {images.slice(0, IMAGE_PREVIEW_COUNT).map((image, index) => (
                        <QuillTicketImageThumbnail key={`${image.url}-${index}`} image={image} />
                    ))}
                    {images.length > IMAGE_PREVIEW_COUNT && (
                        <Text size="xs" weight="medium" render={<li />}>
                            {ticketUrl ? (
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={ticketUrl} />}
                                >
                                    {moreImagesLabel}
                                </Button>
                            ) : (
                                <span className="text-muted-foreground">{moreImagesLabel}</span>
                            )}
                        </Text>
                    )}
                </ul>
            )}
            <Text
                size="xs"
                variant="muted"
                render={<div />}
                className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1"
            >
                {typeof extra.ticket_number === 'number' && (
                    <span className="me-auto font-mono font-medium">{`#${extra.ticket_number}`}</span>
                )}
                {ticketUrl ? (
                    <QuillSignalCardLink to={ticketUrl} data-attr="inbox-evidence-open-ticket">
                        Open ticket
                        <IconChevronRight />
                    </QuillSignalCardLink>
                ) : (
                    <span>Source ticket unavailable</span>
                )}
            </Text>
        </QuillSignalCardShell>
    )
}
