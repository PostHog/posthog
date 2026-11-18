import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { emailDomainSetupPath, startEmailDomainSetup } from '../../Channels/EmailDomain/emailDomainSetupLinks'
import { sendingDomainLogic } from './sendingDomainLogic'

export function SendingDomainRow(): JSX.Element | null {
    const { sendingDomain, integrationsFailed } = useValues(sendingDomainLogic)
    const { loadIntegrations } = useActions(integrationsLogic)

    if (integrationsFailed) {
        return (
            <LemonCard hoverEffect={false} className="flex flex-wrap items-center gap-2 px-4 py-3">
                <IconWarning className="text-warning text-lg shrink-0" />
                <span className="flex-1 min-w-0">Couldn't load your sending domain.</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => loadIntegrations()}
                    data-attr="send-from-code-reload-domain"
                >
                    Try again
                </LemonButton>
            </LemonCard>
        )
    }
    if (!sendingDomain) {
        return <LemonSkeleton className="h-14" />
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-wrap items-center gap-2 px-4 py-3">
            {sendingDomain.status === 'verified' ? (
                <>
                    <IconCheckCircle className="text-success text-lg shrink-0" />
                    <span className="flex-1 min-w-0">
                        Sending from <code className="break-all">{sendingDomain.email}</code>
                    </span>
                    <LemonTag type="success">Domain verified</LemonTag>
                </>
            ) : sendingDomain.status === 'pending' ? (
                <>
                    <IconCircleDashed className="text-secondary text-lg shrink-0" />
                    <span className="flex-1 min-w-0">
                        <code className="break-all">{sendingDomain.domain}</code> is waiting for its DNS records. Emails
                        to your users need a verified domain.
                    </span>
                    <LemonButton
                        type="primary"
                        size="small"
                        to={emailDomainSetupPath(sendingDomain.integrationId, 'transactional')}
                        data-attr="send-from-code-check-dns-records"
                    >
                        Check DNS records
                    </LemonButton>
                </>
            ) : (
                <>
                    <IconCircleDashed className="text-secondary text-lg shrink-0" />
                    <span className="flex-1 min-w-0">
                        Set up the domain you send from. Emails to your users need a verified domain.
                    </span>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => startEmailDomainSetup('transactional', 'transactional')}
                        data-attr="send-from-code-set-up-domain"
                    >
                        Set up a domain
                    </LemonButton>
                </>
            )}
        </LemonCard>
    )
}
