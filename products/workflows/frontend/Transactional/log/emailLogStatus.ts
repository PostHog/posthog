import type { LemonTagType } from '@posthog/lemon-ui'

import type {
    EmailDeliveryStatusEnumApi,
    EmailLogEventKindEnumApi,
} from 'products/messaging/frontend/generated/api.schemas'

export const EMAIL_STATUS_LABEL: Record<EmailLogEventKindEnumApi, string> = {
    queued: 'Queued',
    sent: 'Sent',
    delivered: 'Delivered',
    bounced: 'Bounced',
    complained: 'Marked as spam',
    failed: 'Failed',
    opened: 'Opened',
    clicked: 'Clicked',
}

export const EMAIL_STATUS_TAG: Record<EmailDeliveryStatusEnumApi, LemonTagType> = {
    queued: 'default',
    sent: 'primary',
    delivered: 'success',
    bounced: 'danger',
    complained: 'danger',
    failed: 'danger',
}

export const EMAIL_STATUS_DESCRIPTION: Record<EmailDeliveryStatusEnumApi, string> = {
    queued: 'Waiting to go out.',
    sent: "Handed to the email provider. It shows as delivered once the recipient's mail server accepts it.",
    delivered: "The recipient's mail server accepted the email.",
    bounced: "The recipient's mail server refused the email.",
    complained: 'The recipient marked the email as spam.',
    failed: 'The email was not sent.',
}

const REASON_TEXT: Record<string, string> = {
    hard: "Hard bounce: the address doesn't exist or can't receive email",
    soft: 'Soft bounce: the mailbox was full or the server was busy',
    unknown: "The mail server didn't say why it bounced",
    provider_error: 'The email provider returned an error',
    provider_rejected: 'The email provider refused the email after accepting it',
    recipient_suppressed: 'The recipient is on the suppression list',
    sending_paused: 'Sending is paused for this email',
    sending_suspended: 'Email sending is suspended for this project',
    recipient_unreachable: "The recipient's address can't receive email",
    missing_recipient: 'The send had no recipient address',
    recipient_opted_out: 'The recipient opted out',
    frequency_capped: 'The recipient hit a frequency cap',
    canceled: 'The send was canceled',
    workflow_unavailable: 'The transactional email was deleted before it went out',
}

export function emailReasonText(reason: string | null | undefined): string | null {
    if (!reason) {
        return null
    }
    return REASON_TEXT[reason] ?? `The send stopped with an error (${reason})`
}
