import { IntegrationType } from '~/types'

import { isDeliverableEmailSender, resolveDefaultEmailSender } from '../../Channels/defaultEmailSender'

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

const senderToVerifyOf = (
    integrations: IntegrationType[],
    defaultIntegrationId: number | null | undefined
): IntegrationType | undefined => {
    const emailSenders = integrations.filter((integration) => integration.kind === 'email')
    return emailSenders.find((integration) => integration.id === defaultIntegrationId) ?? emailSenders[0]
}

export function sendingDomainOf(
    integrations: IntegrationType[],
    defaultIntegrationId: number | null | undefined
): SendingDomain {
    const deliverable = integrations.filter(isDeliverableEmailSender)
    const defaultSender = resolveDefaultEmailSender(integrations, defaultIntegrationId)
    const sender = deliverable.find((integration) => integration.id === defaultSender?.integrationId) ?? deliverable[0]
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
    const pending = senderToVerifyOf(integrations, defaultIntegrationId)
    if (pending) {
        return { status: 'pending', integrationId: pending.id, domain: fieldsOf(pending).domain ?? '' }
    }
    return { status: 'none' }
}
