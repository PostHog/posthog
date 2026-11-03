import { ApiConfig } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { isSandboxEmailSender } from 'lib/integrations/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { IntegrationType } from '~/types'

import { integrationsEmailSandboxSenderCreate } from 'products/integrations/frontend/generated/api'

import {
    DefaultEmailSender,
    allowsSandboxSender,
    resolveDefaultEmailSender,
    verifiedOwnEmailSenders,
} from '../Channels/defaultEmailSender'
import type { HogFlow, HogFlowAction } from './hogflows/types'

type EmailStepValue = { from?: { integrationId?: number; email?: string; name?: string }; replyTo?: string }

function emailStepValue(action: HogFlowAction): EmailStepValue | null {
    const config = action.config as Record<string, any> | undefined
    return config?.template_id === 'template-email' ? (config.inputs?.email?.value ?? null) : null
}

function takesOwnSender(action: HogFlowAction): boolean {
    const value = emailStepValue(action)
    return !!value && !value.from?.integrationId
}

function takesSandboxSender(action: HogFlowAction, workflow: HogFlow): boolean {
    const value = emailStepValue(action)
    return (
        !!value &&
        allowsSandboxSender(action.type, workflow.origin_product) &&
        !value.from?.integrationId &&
        !value.from?.email &&
        !value.from?.name &&
        !value.replyTo
    )
}

function withSender(action: HogFlowAction, integrationId: number): HogFlowAction {
    const config = action.config as Record<string, any>
    const email = config.inputs.email
    return {
        ...action,
        config: {
            ...config,
            inputs: {
                ...config.inputs,
                email: { ...email, value: { ...email.value, from: { ...email.value.from, integrationId } } },
            },
        },
    } as HogFlowAction
}

function sandboxSenderEnabled(): boolean {
    return !!featureFlagLogic.findMounted()?.values.featureFlags[FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]
}

async function loadAllIntegrations(): Promise<IntegrationType[]> {
    await integrationsLogic.asyncActions.loadIntegrations()
    const integrations = integrationsLogic.values.integrations
    if (!integrations || integrationsLogic.values.integrationsLoadFailed) {
        throw new Error('The sender list could not load.')
    }
    return integrations
}

async function provisionSandboxSender(): Promise<number> {
    const sandbox = await integrationsEmailSandboxSenderCreate(String(ApiConfig.getCurrentProjectId()))
    await integrationsLogic.asyncActions.loadIntegrations()
    return sandbox.id
}

function teamDefaultSenderId(): number | null | undefined {
    const team = teamLogic.findMounted()?.values.currentTeam
    return team && 'workflows_config' in team ? team.workflows_config?.default_email_integration_id : null
}

function sandboxApplies(integrations: IntegrationType[], sandboxAllowed: boolean): boolean {
    return sandboxAllowed && sandboxSenderEnabled() && verifiedOwnEmailSenders(integrations).length === 0
}

function chooseSender(integrations: IntegrationType[], sandboxAllowed: boolean): DefaultEmailSender | null {
    const sandbox = integrations.find(isSandboxEmailSender)
    return sandbox && sandboxApplies(integrations, sandboxAllowed)
        ? { integrationId: sandbox.id, reason: 'sandbox_sender' }
        : resolveDefaultEmailSender(integrations, teamDefaultSenderId())
}

async function resolveFirstRunSender(allowSandbox: boolean): Promise<DefaultEmailSender | null> {
    const unmountIntegrations = integrationsLogic.mount()
    try {
        const integrations = await loadAllIntegrations()
        if (!sandboxApplies(integrations, allowSandbox) || integrations.some(isSandboxEmailSender)) {
            return chooseSender(integrations, allowSandbox)
        }
        return { integrationId: await provisionSandboxSender(), reason: 'sandbox_sender' }
    } finally {
        unmountIntegrations()
    }
}

export async function prepareSandboxSender(): Promise<void> {
    if (sandboxSenderEnabled() && !integrationsLogic.findMounted()?.values.sandboxEmailSender) {
        await resolveFirstRunSender(true)
    }
}

export function withInsertedStepSender(
    action: HogFlowAction,
    workflow: HogFlow,
    integrations: IntegrationType[] | null
): { action: HogFlowAction; sender: DefaultEmailSender | null } {
    const sender = takesOwnSender(action)
        ? chooseSender(integrations ?? [], takesSandboxSender(action, workflow))
        : null
    return { action: sender ? withSender(action, sender.integrationId) : action, sender }
}

export async function withFirstRunSender(
    workflow: HogFlow
): Promise<{ workflow: HogFlow; sender: DefaultEmailSender | null }> {
    if (!workflow.actions.some(takesOwnSender)) {
        return { workflow, sender: null }
    }
    const sender = await resolveFirstRunSender(workflow.actions.some((action) => takesSandboxSender(action, workflow)))
    if (!sender) {
        return { workflow, sender: null }
    }
    const takesSender = (action: HogFlowAction): boolean =>
        sender.reason === 'sandbox_sender' ? takesSandboxSender(action, workflow) : takesOwnSender(action)
    return {
        workflow: {
            ...workflow,
            actions: workflow.actions.map((action) =>
                takesSender(action) ? withSender(action, sender.integrationId) : action
            ),
        },
        sender,
    }
}
