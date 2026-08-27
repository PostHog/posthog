import { useState } from 'react'

import { IconChevronRight, IconComment, IconGithub, IconImage, IconLetter } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconMicrosoftTeams, IconSlack } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTag, type LemonTagType } from 'lib/lemon-ui/LemonTag'
import { isTrustedPostHogUrl } from 'lib/utils/trustedUrl'
import { urls } from 'scenes/urls'

import type {
    ConversationsTicketImageApi,
    ConversationsTicketSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'
import { safeHttpUrl } from 'products/signals/frontend/inbox/utils/reportPresentation'

import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Guard for Conversations ticket extras. Keys on the ticket number + channel source unique to this source. */
export function isConversationsTicketExtra(
    value: unknown
): value is Record<string, unknown> & ConversationsTicketSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'ticket_number' in extra && 'channel_source' in extra
}

/** Sentence-case a lower-case token, treating underscores as spaces (e.g. `on_hold` → "On hold"). */
function humanizeToken(value: string): string {
    const spaced = value.replace(/_/g, ' ')
    return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** Map a Conversations ticket status to a tag colour. */
export function conversationsStatusTagType(s: string): LemonTagType {
    switch (s) {
        case 'resolved':
            return 'success'
        case 'new':
            return 'primary'
        case 'open':
        case 'pending':
        case 'on_hold':
        default:
            return 'default'
    }
}

/** Human label for a Conversations ticket status (Sentence-cased, underscores humanized). */
export function conversationsStatusLabel(s: string): string {
    return humanizeToken(s)
}

/** Map a Conversations ticket priority to a tag colour. */
export function conversationsPriorityTagType(p: string): LemonTagType {
    switch (p) {
        case 'high':
            return 'danger'
        case 'medium':
            return 'warning'
        case 'low':
        default:
            return 'default'
    }
}

/** Map a channel source to its brand icon, or null when unrecognized. */
export function conversationsChannelIcon(source: string): JSX.Element | null {
    switch (source) {
        case 'widget':
            return <IconComment />
        case 'email':
            return <IconLetter />
        case 'github':
            return <IconGithub />
        case 'slack':
            return <IconSlack />
        case 'teams':
            return <IconMicrosoftTeams />
        default:
            return null
    }
}

/** How many attachment thumbnails to show before pointing at the ticket for the rest. */
const IMAGE_PREVIEW_COUNT = 4

/**
 * One attachment thumbnail that opens the full image. Only an image PostHog serves loads inline: the
 * URL comes from ticket rich content, which is not origin-validated, and an inline `<img>` makes every
 * viewer's browser fetch it on render. Any other host is a click-to-open tile that loads nothing.
 * Drops out when the image can no longer be fetched.
 */
function TicketImageThumbnail({ image }: { image: ConversationsTicketImageApi }): JSX.Element | null {
    const [failed, setFailed] = useState(false)
    const trusted = isTrustedPostHogUrl(image.url)
    const href = trusted ? image.url : safeHttpUrl(image.url)
    if (failed || !href) {
        return null
    }
    const label = image.author ? `Attachment from ${image.author}` : 'Ticket attachment'
    return (
        <li>
            <Link
                to={href}
                target="_blank"
                className="flex items-center justify-center size-16 rounded border overflow-hidden bg-surface-secondary"
                title={image.author ? `Attached by ${image.author}` : undefined}
                aria-label={trusted ? undefined : label}
            >
                {trusted ? (
                    <img
                        src={href}
                        alt={label}
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
    const redesign = useFeatureFlag('INBOX_REDESIGN')
    const extra = signal.extra as Record<string, unknown> & ConversationsTicketSignalExtraApi
    const channelIcon = conversationsChannelIcon(extra.channel_source)
    // Attachment thumbnails are part of the redesign's evidence rail.
    const images = redesign && Array.isArray(extra.images) ? extra.images : []
    const ticketUrl = urls.supportTicketDetail(extra.ticket_number)

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
                        <li>
                            <Link to={ticketUrl} className="text-xs font-medium">
                                +{images.length - IMAGE_PREVIEW_COUNT} more
                            </Link>
                        </li>
                    )}
                </ul>
            )}
            <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary">
                <span className="font-mono font-medium">#{extra.ticket_number}</span>
                <LemonTag size="small" type={conversationsStatusTagType(extra.status)}>
                    {conversationsStatusLabel(extra.status)}
                </LemonTag>
                {extra.priority && (
                    <LemonTag size="small" type={conversationsPriorityTagType(extra.priority)}>
                        {humanizeToken(extra.priority)}
                    </LemonTag>
                )}
                <LemonTag size="small" type="muted">
                    <span className="flex items-center gap-1">
                        {channelIcon}
                        <span>
                            {extra.channel_source}
                            {extra.channel_detail && ` · ${humanizeToken(extra.channel_detail)}`}
                        </span>
                    </span>
                </LemonTag>
            </div>
            <div className="flex items-center mt-2">
                <span className="flex-1" />
                <Link to={ticketUrl} className="flex items-center gap-1 text-xs font-medium">
                    Open ticket
                    <IconChevronRight />
                </Link>
            </div>
        </SignalCardShell>
    )
}

export const conversationsTicketSignalCardEntry: SignalCardEntry = {
    key: 'conversations',
    matches: (signal) => signal.source_product === 'conversations' && isConversationsTicketExtra(signal.extra),
    Component: ConversationsTicketSignalCard,
}
