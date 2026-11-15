import { router } from 'kea-router'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

type EmailDomainSetupEntry = 'channels' | 'broadcast' | 'add_sender'

export function openEmailDomainSetupPage(entry: EmailDomainSetupEntry): void {
    // pinned: analytics event name
    posthog.capture('email domain setup started', { entry })
    router.actions.push(urls.workflowsEmailDomain('new'))
}
