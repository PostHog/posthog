import { router } from 'kea-router'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

export type EmailDomainSetupEntry = 'channels' | 'broadcast' | 'add_sender' | 'transactional' | 'configure'

export const emailDomainSetupPath = (id: number | 'new'): string => urls.workflowsEmailDomain(id)

export const emailDomainSetupPageUrl = (teamId: number, integrationId: number): string =>
    `${window.location.origin}/project/${teamId}${emailDomainSetupPath(integrationId)}`

export function captureEmailDomainSetupStarted(entry: EmailDomainSetupEntry): void {
    // pinned: analytics event name
    posthog.capture('email domain setup started', { entry })
}

export function startEmailDomainSetup(entry: EmailDomainSetupEntry): void {
    captureEmailDomainSetupStarted(entry)
    router.actions.push(emailDomainSetupPath('new'))
}
