import { IntegrationType } from '~/types'

import { isVerifiedEmailSender, resolveDefaultEmailSender } from '../../Channels/defaultEmailSender'

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

export function sendingDomainOf(
    integrations: IntegrationType[],
    defaultIntegrationId: number | null | undefined
): SendingDomain {
    const verified = integrations.filter(isVerifiedEmailSender)
    const defaultSender = resolveDefaultEmailSender(integrations, defaultIntegrationId)
    const sender = verified.find((integration) => integration.id === defaultSender?.integrationId) ?? verified[0]
    if (sender) {
        const { domain = '', email = '', name } = fieldsOf(sender)
        return {
            status: 'verified',
            integrationId: sender.id,
            domain,
            email,
            from: name ? `${name} <${email}>` : email,
        }
    }
    const pending = integrations.find((integration) => integration.kind === 'email')
    if (pending) {
        return { status: 'pending', integrationId: pending.id, domain: fieldsOf(pending).domain ?? '' }
    }
    return { status: 'none' }
}
