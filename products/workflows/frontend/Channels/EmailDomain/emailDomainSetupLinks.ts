import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { DEFAULT_EMAIL_DOMAIN_SETUP_ORIGIN, EmailDomainSetupOrigin, originSearchParams } from './emailDomainSetupOrigin'

export type EmailDomainSetupEntry =
    | 'channels'
    | 'broadcast'
    | 'add_sender'
    | 'transactional'
    | 'configure'
    | 'sandbox_sender_banner'

export const emailDomainSetupPath = (
    id: number | 'new',
    origin: EmailDomainSetupOrigin = DEFAULT_EMAIL_DOMAIN_SETUP_ORIGIN
): string => combineUrl(urls.workflowsEmailDomain(id), originSearchParams(origin)).url

export const emailDomainSetupPageUrl = (
    teamId: number,
    integrationId: number,
    origin: EmailDomainSetupOrigin = DEFAULT_EMAIL_DOMAIN_SETUP_ORIGIN
): string => `${window.location.origin}/project/${teamId}${emailDomainSetupPath(integrationId, origin)}`

export function captureEmailDomainSetupStarted(entry: EmailDomainSetupEntry): void {
    // pinned: analytics event name
    posthog.capture('email domain setup started', { entry })
}

export function startEmailDomainSetup(
    entry: EmailDomainSetupEntry,
    origin: EmailDomainSetupOrigin = DEFAULT_EMAIL_DOMAIN_SETUP_ORIGIN
): void {
    captureEmailDomainSetupStarted(entry)
    router.actions.push(emailDomainSetupPath('new', origin))
}
