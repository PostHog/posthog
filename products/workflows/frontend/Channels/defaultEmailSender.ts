import { isSandboxEmailSender } from 'lib/integrations/sandboxEmailSender'

import { IntegrationType, TeamPublicType, TeamType } from '~/types'

export type DefaultEmailSenderReason = 'project_default' | 'only_verified_sender' | 'sandbox_sender'

export interface DefaultEmailSender {
    integrationId: number
    reason: DefaultEmailSenderReason
}

export function teamDefaultEmailSenderId(
    team: TeamType | TeamPublicType | null | undefined
): number | null | undefined {
    return team && 'workflows_config' in team ? team.workflows_config?.default_email_integration_id : null
}

export function verifiedOwnEmailSenders(integrations: IntegrationType[] | null | undefined): IntegrationType[] {
    return (integrations ?? []).filter(
        (integration) =>
            integration.kind === 'email' && !isSandboxEmailSender(integration) && integration.config?.verified === true
    )
}

export function resolveDefaultEmailSender(
    integrations: IntegrationType[] | null | undefined,
    defaultIntegrationId: number | null | undefined
): DefaultEmailSender | null {
    const verified = verifiedOwnEmailSenders(integrations)
    const projectDefault = verified.find((integration) => integration.id === defaultIntegrationId)
    if (projectDefault) {
        return { integrationId: projectDefault.id, reason: 'project_default' }
    }
    if (verified.length === 1) {
        return { integrationId: verified[0].id, reason: 'only_verified_sender' }
    }
    return null
}
