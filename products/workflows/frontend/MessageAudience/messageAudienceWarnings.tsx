import { router } from 'kea-router'

import { LemonDialog } from '@posthog/lemon-ui'

import { ApiConfig } from 'lib/api'
import { isSandboxEmailSender } from 'lib/integrations/utils'
import { urls } from 'scenes/urls'

import { cohortsRetrieve } from 'products/cohorts/frontend/generated/api'
import { integrationsList } from 'products/integrations/frontend/generated/api'
import type { IntegrationConfigApi } from 'products/integrations/frontend/generated/api.schemas'
import { hogFlowsEmailSendingSuspensionRetrieve } from 'products/workflows/frontend/generated/api'

import { audienceCohortIds, audienceCohortLaunchError, toAudienceCohort } from '../Broadcasts/audience/audienceList'
import {
    EMAIL_SENDING_SUSPENDED_MESSAGE,
    NO_EMAIL_SENDER_MESSAGE,
    SANDBOX_ONLY_SENDER_MESSAGE,
    UNVERIFIED_SENDER_MESSAGE,
} from '../Channels/emailSendingMessages'
import { MessageAudience, MessageAudienceDestination, messageAudienceUrl } from './messageAudience'

export function emailSenderWarning(integrations: Pick<IntegrationConfigApi, 'kind' | 'config'>[]): string | null {
    const emailIntegrations = integrations.filter((integration) => integration.kind === 'email')
    const senders = emailIntegrations.filter((integration) => !isSandboxEmailSender(integration))
    if (senders.length === 0) {
        return emailIntegrations.length > 0 ? SANDBOX_ONLY_SENDER_MESSAGE : NO_EMAIL_SENDER_MESSAGE
    }
    const verified = senders.some(
        (integration) => (integration.config as { verified?: boolean } | undefined)?.verified === true
    )
    return verified ? null : UNVERIFIED_SENDER_MESSAGE
}

// The checks only advise, so a slow one must not hold the person on the page.
const CHECK_TIMEOUT_MS = 5000

function withinTimeout<T>(request: Promise<T>): Promise<T | null> {
    return Promise.race([
        request.catch(() => null),
        new Promise<null>((resolve) => setTimeout(() => resolve(null), CHECK_TIMEOUT_MS)),
    ])
}

/**
 * What would stop the email from going out, checked when the person clicks so the entry point costs nothing
 * on page view. A check that fails or times out stays quiet: the broadcast launch and the workflow editor check again.
 */
export async function loadMessageAudienceWarnings(
    audience: MessageAudience,
    destination: MessageAudienceDestination
): Promise<string[]> {
    const projectId = String(ApiConfig.getCurrentProjectId())
    // A workflow sends per person as they qualify, so a cohort that is still calculating doesn't hold it up.
    const cohortIds = destination === 'broadcast' ? audienceCohortIds(audience.properties) : []
    const [suspension, integrations, cohorts] = await Promise.all([
        withinTimeout(hogFlowsEmailSendingSuspensionRetrieve(projectId)),
        withinTimeout(integrationsList(projectId, { kind: 'email' })),
        Promise.all(
            cohortIds.map((id) =>
                withinTimeout(cohortsRetrieve(projectId, id).then((cohort) => toAudienceCohort(id, cohort)))
            )
        ),
    ])
    return [
        suspension?.email_sending_suspended ? EMAIL_SENDING_SUSPENDED_MESSAGE : null,
        // A verified sender can sit on a later page, so only a complete list can say none is verified.
        integrations && !integrations.next ? emailSenderWarning(integrations.results) : null,
        ...cohorts.map((cohort) => (cohort ? audienceCohortLaunchError(cohort) : null)),
    ].filter((warning): warning is string => !!warning)
}

let opening = false

/**
 * Opens the broadcast or workflow, asking first when something would stop the email from going out. A second click
 * while the checks run does nothing.
 */
export async function openMessageAudience(
    audience: MessageAudience,
    destination: MessageAudienceDestination
): Promise<void> {
    if (opening) {
        return
    }
    opening = true
    try {
        const navigate = async (): Promise<void> => {
            router.actions.push(messageAudienceUrl(audience, destination))
        }
        const startedOn = router.values.location.pathname
        const warnings = await loadMessageAudienceWarnings(audience, destination)
        if (router.values.location.pathname !== startedOn) {
            // The person left the page while the checks ran.
            return
        }
        if (warnings.length === 0) {
            await navigate()
            return
        }
        // The modal covers the entry point, and Continue shows its own loading state while it opens the email.
        LemonDialog.open({
            title: 'Before you send',
            content: (
                <ul className="list-disc pl-4 m-0 flex flex-col gap-1" data-attr="message-audience-warnings">
                    {warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                    ))}
                </ul>
            ),
            shouldAwaitSubmit: true,
            primaryButton: {
                children: 'Continue',
                onClick: navigate,
                'data-attr': `message-audience-${audience.source}-continue`,
            },
            secondaryButton: [NO_EMAIL_SENDER_MESSAGE, SANDBOX_ONLY_SENDER_MESSAGE, UNVERIFIED_SENDER_MESSAGE].some(
                (message) => warnings.includes(message)
            )
                ? { children: 'Set up email', onClick: () => router.actions.push(urls.workflows('channels')) }
                : { children: 'Cancel' },
        })
    } finally {
        opening = false
    }
}
