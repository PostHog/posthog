import { router } from 'kea-router'

import { LemonDialog } from '@posthog/lemon-ui'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { cohortsRetrieve } from 'products/cohorts/frontend/generated/api'
import { integrationsList } from 'products/integrations/frontend/generated/api'
import type { IntegrationConfigApi } from 'products/integrations/frontend/generated/api.schemas'
import { hogFlowsEmailSendingSuspensionRetrieve } from 'products/workflows/frontend/generated/api'

import { audienceCohortIds, audienceCohortLaunchError, toAudienceCohort } from '../Broadcasts/audience/audienceList'
import {
    EMAIL_SENDING_SUSPENDED_MESSAGE,
    NO_EMAIL_SENDER_MESSAGE,
    UNVERIFIED_SENDER_MESSAGE,
} from '../Channels/emailSendingMessages'
import { MessageAudience, MessageAudienceDestination, messageAudienceUrl } from './messageAudience'

export function emailSenderWarning(integrations: Pick<IntegrationConfigApi, 'kind' | 'config'>[]): string | null {
    const senders = integrations.filter((integration) => integration.kind === 'email')
    if (senders.length === 0) {
        return NO_EMAIL_SENDER_MESSAGE
    }
    const verified = senders.some(
        (integration) => (integration.config as { verified?: boolean } | undefined)?.verified === true
    )
    return verified ? null : UNVERIFIED_SENDER_MESSAGE
}

/**
 * What would stop the email from going out, checked when the person clicks so the entry point costs nothing
 * on page view. A check that fails stays quiet: the broadcast launch and the workflow editor check again.
 */
export async function loadMessageAudienceWarnings(
    audience: MessageAudience,
    destination: MessageAudienceDestination
): Promise<string[]> {
    const projectId = String(ApiConfig.getCurrentProjectId())
    // A workflow sends per person as they qualify, so a cohort that is still calculating doesn't hold it up.
    const cohortIds = destination === 'broadcast' ? audienceCohortIds(audience.properties) : []
    const [suspension, integrations, cohorts] = await Promise.all([
        hogFlowsEmailSendingSuspensionRetrieve(projectId).catch(() => null),
        integrationsList(projectId, { kind: 'email' }).catch(() => null),
        Promise.all(
            cohortIds.map((id) =>
                cohortsRetrieve(projectId, id)
                    .then((cohort) => toAudienceCohort(id, cohort))
                    .catch(() => null)
            )
        ),
    ])
    return [
        suspension?.email_sending_suspended ? EMAIL_SENDING_SUSPENDED_MESSAGE : null,
        integrations ? emailSenderWarning(integrations.results) : null,
        ...cohorts.map((cohort) => (cohort ? audienceCohortLaunchError(cohort) : null)),
    ].filter((warning): warning is string => !!warning)
}

/** Opens the broadcast or workflow, asking first when something would stop the email from going out. */
export async function openMessageAudience(
    audience: MessageAudience,
    destination: MessageAudienceDestination
): Promise<void> {
    const navigate = (): void => router.actions.push(messageAudienceUrl(audience, destination))
    const warnings = await loadMessageAudienceWarnings(audience, destination)
    if (warnings.length === 0) {
        navigate()
        return
    }
    LemonDialog.open({
        title: 'Before you send',
        content: (
            <ul className="list-disc pl-4 m-0 flex flex-col gap-1" data-attr="message-audience-warnings">
                {warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                ))}
            </ul>
        ),
        primaryButton: {
            children: 'Continue',
            onClick: navigate,
            'data-attr': `message-audience-${audience.source}-continue`,
        },
        secondaryButton:
            warnings.includes(NO_EMAIL_SENDER_MESSAGE) || warnings.includes(UNVERIFIED_SENDER_MESSAGE)
                ? { children: 'Set up email', onClick: () => router.actions.push(urls.workflows('channels')) }
                : { children: 'Cancel' },
    })
}
