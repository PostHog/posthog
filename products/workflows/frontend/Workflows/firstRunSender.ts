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

async function resolveFirstRunSender(allowSandbox: boolean): Promise<DefaultEmailSender | null> {
    const team = teamLogic.findMounted()?.values.currentTeam
    const integrations = await loadAllIntegrations()
    const ownSender = resolveDefaultEmailSender(
        integrations,
        team && 'workflows_config' in team ? team.workflows_config?.default_email_integration_id : null
    )
    if (ownSender || !allowSandbox || !sandboxSenderEnabled() || verifiedOwnEmailSenders(integrations).length > 0) {
        return ownSender
    }
    const sandbox = integrations.find(isSandboxEmailSender)
    return { integrationId: sandbox?.id ?? (await provisionSandboxSender()), reason: 'sandbox_sender' }
}

export async function withFirstRunSender(
    workflow: HogFlow
): Promise<{ workflow: HogFlow; sender: DefaultEmailSender | null }> {
    if (!workflow.actions.some(takesOwnSender)) {
        return { workflow, sender: null }
    }
    const unmountIntegrations = integrationsLogic.mount()
    const sender = await resolveFirstRunSender(
        workflow.actions.some((action) => takesSandboxSender(action, workflow))
    ).finally(unmountIntegrations)
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
