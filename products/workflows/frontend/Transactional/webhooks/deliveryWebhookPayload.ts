import { CyclotronJobFiltersType, EventPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { hogFunctionsCreate } from 'products/cdp/frontend/generated/api'

export type DeliveryWebhookCreateBody = NonNullable<Parameters<typeof hogFunctionsCreate>[1]>

export const DELIVERY_WEBHOOK_TEMPLATE_ID = 'template-webhook'

export const DELIVERY_WEBHOOK_EVENTS = [
    { event: '$workflows_email_sent', label: 'Sent' },
    { event: '$workflows_email_delivered', label: 'Delivered' },
    { event: '$workflows_email_bounced', label: 'Bounced' },
    { event: '$workflows_email_blocked', label: 'Marked as spam' },
    { event: '$workflows_email_failed', label: 'Failed' },
    { event: '$workflows_email_opened', label: 'Opened' },
    { event: '$workflows_email_link_clicked', label: 'Link clicked' },
] as const

export type DeliveryWebhookEventName = (typeof DELIVERY_WEBHOOK_EVENTS)[number]['event']

const TRANSACTIONAL_EMAIL_PROPERTY: EventPropertyFilter = {
    key: '$email_transactional',
    type: PropertyFilterType.Event,
    operator: PropertyOperator.IsSet,
}

export const DELIVERY_WEBHOOK_LIST_FILTER_GROUPS: CyclotronJobFiltersType[] = [
    { properties: [TRANSACTIONAL_EMAIL_PROPERTY] },
]

const DELIVERY_WEBHOOK_BODY = {
    type: "{event.event == '$workflows_email_blocked' ? 'email.complained' : event.event == '$workflows_email_link_clicked' ? 'email.clicked' : replaceOne(event.event, '$workflows_email_', 'email.')}",
    created_at: '{event.timestamp}',
    data: {
        created_at: '{event.timestamp}',
        email_id: '{event.properties.$workflow_invocation_id}',
        to: ['{event.properties.$email_to}'],
        subject: '{event.properties.$email_subject}',
        distinct_id: '{event.distinct_id}',
        bounce: {
            type: "{event.properties.$bounce_type == 'hard' ? 'Permanent' : event.properties.$bounce_type == 'soft' ? 'Transient' : event.properties.$bounce_type == 'unknown' ? 'Undetermined' : null}",
            subType: '{event.properties.$bounce_sub_type}',
        },
        click: { link: '{event.properties.$link_url}' },
    },
}

export function generateSigningSecret(): string {
    const bytes = crypto.getRandomValues(new Uint8Array(32))
    return `whsec_${btoa(String.fromCharCode(...bytes))}`
}

const NAME_PATH_LENGTH = 30

function shortPath(pathname: string): string {
    if (pathname === '/') {
        return ''
    }
    return pathname.length > NAME_PATH_LENGTH ? `${pathname.slice(0, NAME_PATH_LENGTH)}…` : pathname
}

export function buildDeliveryWebhookPayload({
    url,
    events,
    workflowIds,
    signingSecret,
}: {
    url: string
    events: DeliveryWebhookEventName[]
    workflowIds: string[]
    signingSecret: string
}): DeliveryWebhookCreateBody {
    const { host, pathname } = new URL(url)
    const payload = {
        template_id: DELIVERY_WEBHOOK_TEMPLATE_ID,
        type: 'destination',
        name: `Transactional email webhook: ${host}${shortPath(pathname)}`,
        description: 'Sends delivery updates for transactional emails to your endpoint.',
        inputs: {
            url: { value: url },
            method: { value: 'POST' },
            headers: { value: { 'Content-Type': 'application/json' } },
            body: { value: DELIVERY_WEBHOOK_BODY },
            signing_secret: { value: signingSecret },
        },
        filters: {
            source: 'events',
            events: events.map((event) => ({ id: event, name: event, type: 'events' })),
            properties: [
                TRANSACTIONAL_EMAIL_PROPERTY,
                ...(workflowIds.length > 0
                    ? [
                          {
                              key: '$workflow_id',
                              type: PropertyFilterType.Event,
                              operator: PropertyOperator.Exact,
                              value: workflowIds,
                          },
                      ]
                    : []),
            ],
        },
        enabled: true,
    }
    return payload as unknown as DeliveryWebhookCreateBody
}
