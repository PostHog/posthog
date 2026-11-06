import { CyclotronJobFiltersType, EventPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { hogFunctionsCreate } from 'products/cdp/frontend/generated/api'
import type { HogFunctionTemplateApi } from 'products/cdp/frontend/generated/api.schemas'

export type DeliveryWebhookCreateBody = NonNullable<Parameters<typeof hogFunctionsCreate>[1]>

export const DELIVERY_WEBHOOK_TEMPLATE_ID = 'template-webhook'

// pinned: event names the email delivery pipeline captures. Renaming one stops its webhooks.
export const DELIVERY_WEBHOOK_EVENTS = [
    { event: '$workflows_email_sent', label: 'Sent' },
    { event: '$workflows_email_delivered', label: 'Delivered' },
    { event: '$workflows_email_delivery_delayed', label: 'Delivery delayed' },
    { event: '$workflows_email_bounced', label: 'Bounced' },
    { event: '$workflows_email_blocked', label: 'Marked as spam' },
    { event: '$workflows_email_failed', label: 'Failed' },
    { event: '$workflows_email_opened', label: 'Opened' },
    { event: '$workflows_email_link_clicked', label: 'Link clicked' },
] as const

// pinned: the event email receiving captures. Renaming it stops its webhooks.
export const RECEIVED_EMAIL_EVENT = '$email_received'

export type DeliveryWebhookEventName = (typeof DELIVERY_WEBHOOK_EVENTS)[number]['event'] | typeof RECEIVED_EMAIL_EVENT

// Only a transactional send or a received email carries the message id, so this property tells their events apart
// from workflow emails.
const TRANSACTIONAL_EMAIL_PROPERTY: EventPropertyFilter = {
    key: '$email_message_id',
    type: PropertyFilterType.Event,
    operator: PropertyOperator.IsSet,
}

// The list matches any destination whose filters contain this group, including one a user built by hand.
export const DELIVERY_WEBHOOK_LIST_FILTER_GROUPS: CyclotronJobFiltersType[] = [
    { properties: [TRANSACTIONAL_EMAIL_PROPERTY] },
]

// Resend's event names, fields and bounce types, so a Resend receiver reads it. It has no `from`, because these
// events do not carry the sender. Resend names a spam complaint "complained" and a link click "clicked".
const DELIVERY_WEBHOOK_BODY = {
    type: "{event.event == '$email_received' ? 'email.received' : event.event == '$workflows_email_blocked' ? 'email.complained' : event.event == '$workflows_email_link_clicked' ? 'email.clicked' : replaceOne(event.event, '$workflows_email_', 'email.')}",
    created_at: '{event.timestamp}',
    data: {
        created_at: '{event.timestamp}',
        email_id: '{event.properties.$email_message_id}',
        to: '{event.properties.$email_to_addresses ?? [event.properties.$email_to]}',
        subject: '{event.properties.$email_subject}',
        distinct_id: '{event.distinct_id}',
        bounce: {
            type: "{event.properties.$bounce_type == 'hard' ? 'Permanent' : event.properties.$bounce_type == 'soft' ? 'Transient' : event.properties.$bounce_type == 'unknown' ? 'Undetermined' : null}",
            subType: '{event.properties.$bounce_sub_type}',
        },
        click: { link: '{event.properties.$link_url}' },
        // Only `email.received` fills these. The body stays out of the payload: `body_included` says so, and
        // `content_url` is where a handler reads it, so nobody builds on a body that was never there.
        from: '{event.properties.$email_from}',
        recipients: '{event.properties.$email_recipients}',
        body_included: '{event.properties.$email_body_included}',
        content_url: '{event.properties.$email_content_url}',
        is_reply: '{event.properties.$email_is_reply}',
        original_email_id: '{event.properties.$email_original_message_id}',
        sender_verified: '{event.properties.$email_sender_verified}',
        authentication: {
            spf: '{event.properties.$email_spf}',
            dkim: '{event.properties.$email_dkim}',
            dmarc: '{event.properties.$email_dmarc}',
        },
        attachment_count: '{event.properties.$email_attachment_count}',
    },
}

/** A Standard Webhooks secret: `whsec_` and 32 random bytes in base64. */
export function generateSigningSecret(): string {
    const bytes = crypto.getRandomValues(new Uint8Array(32))
    return `whsec_${btoa(String.fromCharCode(...bytes))}`
}

export function isHttpsUrl(value: string): boolean {
    try {
        return new URL(value).protocol === 'https:'
    } catch {
        return false
    }
}

function hostOf(url: string): string {
    try {
        return new URL(url).host
    } catch {
        return url
    }
}

export function buildDeliveryWebhookPayload({
    url,
    events,
    receivedRecipient = '',
    signingSecret,
    template,
}: {
    url: string
    events: DeliveryWebhookEventName[]
    /** Sends received email to this webhook only when it was delivered to an address containing this. */
    receivedRecipient?: string
    signingSecret: string
    template: Pick<HogFunctionTemplateApi, 'code' | 'inputs_schema' | 'icon_url'>
}): DeliveryWebhookCreateBody {
    const payload = {
        template_id: DELIVERY_WEBHOOK_TEMPLATE_ID,
        type: 'destination',
        name: `Transactional email webhook: ${hostOf(url)}`,
        description: 'Sends delivery updates for transactional emails to your endpoint.',
        hog: template.code,
        inputs_schema: template.inputs_schema,
        inputs: {
            url: { value: url },
            method: { value: 'POST' },
            headers: { value: { 'Content-Type': 'application/json' } },
            body: { value: DELIVERY_WEBHOOK_BODY },
            signing_secret: { value: signingSecret },
        },
        filters: {
            source: 'events',
            events: events.map((event) => ({
                id: event,
                name: event,
                type: 'events',
                ...(event === RECEIVED_EMAIL_EVENT && receivedRecipient.trim()
                    ? {
                          properties: [
                              {
                                  key: '$email_recipients',
                                  type: PropertyFilterType.Event,
                                  operator: PropertyOperator.IContains,
                                  value: receivedRecipient.trim().toLowerCase(),
                              },
                          ],
                      }
                    : {}),
            })),
            properties: [TRANSACTIONAL_EMAIL_PROPERTY],
        },
        icon_url: template.icon_url,
        enabled: true,
    }
    // The generated write body marks server-set input fields (bytecode, order, transpiled) as required,
    // so the payload reaches it only through `unknown`.
    return payload as unknown as DeliveryWebhookCreateBody
}
