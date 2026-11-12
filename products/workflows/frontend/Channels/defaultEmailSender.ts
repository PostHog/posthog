export type DefaultEmailSenderReason = 'project_default' | 'only_verified_sender'

export interface DefaultEmailSender {
    integrationId: number
    reason: DefaultEmailSenderReason
}

export interface EmailSenderCandidate {
    id: number
    kind: string
    config?: unknown
}

export function isVerifiedEmailSender(integration: EmailSenderCandidate): boolean {
    return integration.kind === 'email' && (integration.config as { verified?: unknown } | undefined)?.verified === true
}

export function resolveDefaultEmailSender(
    integrations: EmailSenderCandidate[] | null | undefined,
    defaultIntegrationId: number | null | undefined
): DefaultEmailSender | null {
    const verified = (integrations ?? []).filter(isVerifiedEmailSender)
    const projectDefault = verified.find((integration) => integration.id === defaultIntegrationId)
    if (projectDefault) {
        return { integrationId: projectDefault.id, reason: 'project_default' }
    }
    if (verified.length === 1) {
        return { integrationId: verified[0].id, reason: 'only_verified_sender' }
    }
    return null
}
