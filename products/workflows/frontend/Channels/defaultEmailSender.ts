import { IntegrationType } from '~/types'

export type DefaultEmailSenderReason = 'project_default' | 'only_verified_sender'

export interface DefaultEmailSender {
    integrationId: number
    reason: DefaultEmailSenderReason
}

export function resolveDefaultEmailSender(
    integrations: IntegrationType[] | null | undefined,
    defaultIntegrationId: number | null | undefined
): DefaultEmailSender | null {
    const verified = (integrations ?? []).filter(
        (integration) => integration.kind === 'email' && integration.config?.verified === true
    )
    const projectDefault = verified.find((integration) => integration.id === defaultIntegrationId)
    if (projectDefault) {
        return { integrationId: projectDefault.id, reason: 'project_default' }
    }
    if (verified.length === 1) {
        return { integrationId: verified[0].id, reason: 'only_verified_sender' }
    }
    return null
}
