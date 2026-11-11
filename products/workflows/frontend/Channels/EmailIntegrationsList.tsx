import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { AddEmailSenderModal } from './EmailDomain/AddEmailSenderModal'
import { IntegrationEmailDomainView } from './IntegrationEmailDomainView'

export function EmailIntegrationsList(): JSX.Element {
    const { integrationsLoading, domainGroupedEmailIntegrations } = useValues(integrationsLogic)
    const addSenderEnabled = useFeatureFlag('WORKFLOWS_EMAIL_DOMAIN_WIZARD')

    return (
        <div className="deprecated-space-y-2">
            {addSenderEnabled && <AddEmailSenderModal />}
            {integrationsLoading ? (
                <LemonSkeleton className="h-10" />
            ) : (
                domainGroupedEmailIntegrations.map((integration) => (
                    <IntegrationEmailDomainView
                        key={integration.domain}
                        integration={integration}
                        canAddSender={addSenderEnabled}
                    />
                ))
            )}
        </div>
    )
}
