import posthog from 'posthog-js'

import { ApiConfig } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { isSandboxEmailSender } from 'lib/integrations/sandboxEmailSender'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { IntegrationKind, IntegrationType } from '~/types'

import { integrationsEmailSandboxSenderCreate, integrationsList } from 'products/integrations/frontend/generated/api'

import {
    DefaultEmailSender,
    allowsSandboxSender,
    resolveDefaultEmailSender,
    verifiedOwnEmailSenders,
} from '../Channels/defaultEmailSender'
import type { HogFlow, HogFlowAction } from './hogflows/types'
import { emailStepValue, takesOwnSender, withEmailSender } from './workflowEmailPrefill'

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

export function sandboxSenderEnabled(): boolean {
    return !!featureFlagLogic.findMounted()?.values.featureFlags[FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]
}

async function loadEveryIntegrationPage(): Promise<IntegrationType[]> {
    const teamId = String(ApiConfig.getCurrentTeamId())
    const integrations: IntegrationType[] = []
    let hasNext = true
    while (hasNext) {
        const page = await integrationsList(teamId, { kind: 'email', limit: 100, offset: integrations.length })
        for (const integration of page.results) {
            integrations.push({
                id: integration.id,
                kind: integration.kind as IntegrationKind,
                display_name: integration.display_name,
                icon_url: '',
                config: integration.config ?? {},
                created_at: integration.created_at,
                errors: integration.errors,
            })
        }
        hasNext = !!page.next && page.results.length > 0
    }
    return integrations
}

async function provisionSandboxSender(): Promise<number> {
    const sandbox = await integrationsEmailSandboxSenderCreate(String(ApiConfig.getCurrentTeamId()))
    await integrationsLogic.findMounted()?.asyncActions.loadIntegrations()
    return sandbox.id
}

function teamDefaultSenderId(): number | null | undefined {
    const team = teamLogic.findMounted()?.values.currentTeam
    return team && 'workflows_config' in team ? team.workflows_config?.default_email_integration_id : null
}

function sandboxApplies(integrations: IntegrationType[], sandboxAllowed: boolean): boolean {
    return sandboxAllowed && sandboxSenderEnabled() && verifiedOwnEmailSenders(integrations).length === 0
}

async function resolveFirstRunSender(allowSandbox: boolean): Promise<DefaultEmailSender | null> {
    try {
        const integrations = await loadEveryIntegrationPage()
        if (!sandboxApplies(integrations, allowSandbox)) {
            return resolveDefaultEmailSender(integrations, teamDefaultSenderId())
        }
        const sandbox = integrations.find(isSandboxEmailSender)
        return { integrationId: sandbox?.id ?? (await provisionSandboxSender()), reason: 'sandbox_sender' }
    } catch (error) {
        posthog.captureException(error, { feature: 'workflows-sandbox-sender', step: 'first-run sender' })
        throw error
    }
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
    const takesSender =
        sender.reason === 'sandbox_sender'
            ? (action: HogFlowAction): boolean => takesSandboxSender(action, workflow)
            : takesOwnSender
    return { workflow: withEmailSender(workflow, sender.integrationId, takesSender).workflow, sender }
}
