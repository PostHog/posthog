import type { IntegrationType } from '~/types'

export type IdeaEmailSender =
    | { status: 'unknown' }
    | { status: 'none' }
    | { status: 'unverified' }
    | { status: 'verified'; integrationId: number; address: string }

/** Whether the project can send an idea's emails yet, and with which sender. */
export function ideaEmailSender(integrations: IntegrationType[] | null): IdeaEmailSender {
    if (integrations === null) {
        return { status: 'unknown' }
    }
    const senders = integrations.filter((integration) => integration.kind === 'email')
    const verified = senders.find((integration) => integration.config?.verified === true)
    if (verified) {
        return {
            status: 'verified',
            integrationId: verified.id,
            address: verified.config?.email ?? verified.display_name,
        }
    }
    return senders.length > 0 ? { status: 'unverified' } : { status: 'none' }
}

/** Points every email step of an idea's workflow at the project's sender, keeping the sender name. */
export function withEmailSender(definition: Record<string, unknown>, integrationId: number): Record<string, unknown> {
    const actions = Array.isArray(definition.actions) ? (definition.actions as Record<string, any>[]) : []
    return {
        ...definition,
        actions: actions.map((action) => {
            const email = action.config?.inputs?.email
            if (action.type !== 'function_email' || !email?.value) {
                return action
            }
            return {
                ...action,
                config: {
                    ...action.config,
                    inputs: {
                        ...action.config.inputs,
                        email: { ...email, value: { ...email.value, from: { ...email.value.from, integrationId } } },
                    },
                },
            }
        }),
    }
}
