import { router } from 'kea-router'
import posthog from 'posthog-js'

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
import { startMessageAudienceAttempt } from './messageAudienceAttempts'

// pinned: analytics property values of the warnings event
export type MessageAudienceWarningKind = 'sending_suspended' | 'no_sender' | 'unverified_sender' | 'cohort_not_ready'

export interface MessageAudienceWarning {
    kind: MessageAudienceWarningKind
    message: string
}

const SENDER_WARNING_KINDS: MessageAudienceWarningKind[] = ['no_sender', 'unverified_sender']

export function emailSenderWarning(
    integrations: Pick<IntegrationConfigApi, 'kind' | 'config'>[]
): MessageAudienceWarning | null {
    const senders = integrations.filter((integration) => integration.kind === 'email')
    if (senders.length === 0) {
        return { kind: 'no_sender', message: NO_EMAIL_SENDER_MESSAGE }
    }
    const verified = senders.some(
        (integration) => (integration.config as { verified?: boolean } | undefined)?.verified === true
    )
    return verified ? null : { kind: 'unverified_sender', message: UNVERIFIED_SENDER_MESSAGE }
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
): Promise<MessageAudienceWarning[]> {
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
        suspension?.email_sending_suspended
            ? { kind: 'sending_suspended' as const, message: EMAIL_SENDING_SUSPENDED_MESSAGE }
            : null,
        // A verified sender can sit on a later page, so only a complete list can say none is verified.
        integrations && !integrations.next ? emailSenderWarning(integrations.results) : null,
        ...cohorts.map((cohort) => {
            const message = cohort ? audienceCohortLaunchError(cohort) : null
            return message ? { kind: 'cohort_not_ready' as const, message } : null
        }),
    ].filter((warning): warning is MessageAudienceWarning => !!warning)
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
        // pinned: analytics event name and properties
        posthog.capture('message audience warnings shown', {
            source: audience.source,
            destination,
            attempt_id: startMessageAudienceAttempt(audience.source, destination).attemptId,
            warnings: warnings.map((warning) => warning.kind),
        })
        // The modal covers the entry point, and Continue shows its own loading state while it opens the email.
        LemonDialog.open({
            title: 'Before you send',
            content: (
                <ul className="list-disc pl-4 m-0 flex flex-col gap-1" data-attr="message-audience-warnings">
                    {warnings.map((warning) => (
                        <li key={warning.kind + warning.message}>{warning.message}</li>
                    ))}
                </ul>
            ),
            shouldAwaitSubmit: true,
            primaryButton: {
                children: 'Continue',
                onClick: navigate,
                'data-attr': `message-audience-${audience.source}-continue`,
            },
            secondaryButton: warnings.some((warning) => SENDER_WARNING_KINDS.includes(warning.kind))
                ? {
                      children: 'Set up email',
                      onClick: () => router.actions.push(urls.workflows('channels')),
                      'data-attr': `message-audience-${audience.source}-set-up-email`,
                  }
                : { children: 'Cancel' },
        })
    } finally {
        opening = false
    }
}
