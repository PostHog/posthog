import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { EmailIntegrationsList } from 'lib/integrations/EmailIntegrationsList'

import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

export function WizardDomainStep(): JSX.Element {
    const { stepDone } = useValues(workflowsOnboardingWizardLogic)

    return (
        <div className="flex flex-col gap-4">
            {stepDone?.domain ? (
                <LemonBanner type="success">Your domain is verified. Your email is ready to send.</LemonBanner>
            ) : (
                <LemonBanner type="info">
                    Open your domain below to see its DNS records. Add them at your DNS provider, then verify. Emails
                    send only after the domain is verified.
                </LemonBanner>
            )}
            <EmailIntegrationsList />
        </div>
    )
}
