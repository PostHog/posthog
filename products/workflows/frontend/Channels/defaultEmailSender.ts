import { isSandboxEmailSender } from 'lib/integrations/utils'

import { IntegrationType } from '~/types'

import type { HogFlowAction } from '../Workflows/hogflows/types'

export type DefaultEmailSenderReason = 'project_default' | 'only_verified_sender' | 'sandbox_sender'

export interface DefaultEmailSender {
    integrationId: number
    reason: DefaultEmailSenderReason
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

export function allowsSandboxSender(
    actionType: HogFlowAction['type'],
    originProduct: string | null | undefined
): boolean {
    return actionType === 'function_email' && originProduct !== 'broadcasts'
}
