import { IntegrationType } from '~/types'

import { isDeliverableEmailSender, isVerifiedEmailSender } from '../../Channels/defaultEmailSender'

export type SendingDomain =
    | { status: 'none' }
    | { status: 'pending'; integrationId: number; domain: string }
    | { status: 'verified'; integrationId: number; domain: string; email: string; from: string }

interface EmailSenderFields {
    domain?: string
    email?: string
    name?: string
}

const fieldsOf = (integration: IntegrationType): EmailSenderFields => (integration.config ?? {}) as EmailSenderFields

// Same specials as Python's email.utils.formataddr, which the send API parses the address with.
const NEEDS_QUOTES = /[\][\\()<>@,:;".]/

export function senderAddress(name: string | undefined, email: string): string {
    if (!name) {
        return email
    }
    const displayName = NEEDS_QUOTES.test(name) ? `"${name.replace(/[\\"]/g, '\\$&')}"` : name
    return `${displayName} <${email}>`
}

export function sendingDomainOf(
    integrations: IntegrationType[],
    defaultIntegrationId: number | null | undefined
): SendingDomain {
    const verified = integrations.filter(isVerifiedEmailSender)
    const deliverable = verified.filter(isDeliverableEmailSender)
    const sender =
        deliverable.find((integration) => integration.id === defaultIntegrationId) ??
        deliverable[0] ??
        verified.find((integration) => integration.id === defaultIntegrationId) ??
        verified[0]
    if (sender) {
        const { domain = '', email = '', name } = fieldsOf(sender)
        return {
            status: 'verified',
            integrationId: sender.id,
            domain,
            email,
            from: senderAddress(name, email),
        }
    }
    const pending = integrations.find((integration) => integration.kind === 'email')
    if (pending) {
        return { status: 'pending', integrationId: pending.id, domain: fieldsOf(pending).domain ?? '' }
    }
    return { status: 'none' }
}
