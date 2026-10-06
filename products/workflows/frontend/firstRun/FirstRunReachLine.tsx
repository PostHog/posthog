import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { firstRunReachCopy } from './firstRunReachCopy'
import { firstRunReachLogic } from './firstRunReachLogic'

function ownDomainSetupUrl(): string {
    return urls.workflows('channels')
}

export function FirstRunReachLine({ senderIntegrationId }: { senderIntegrationId: number | null }): JSX.Element | null {
    const { reach } = useValues(firstRunReachLogic({ senderIntegrationId }))

    if (!reach) {
        return null
    }

    return (
        <div className="flex flex-col gap-2 items-start font-normal" data-attr="workflows-first-run-reach">
            <span>
                Sends from <strong translate="no">{reach.senderAddress}</strong> {firstRunReachCopy(reach)}
            </span>
            <LemonButton
                type="secondary"
                size="small"
                to={ownDomainSetupUrl()}
                data-attr="workflows-first-run-own-domain"
            >
                {reach.ownDomain === 'verifying' ? 'Finish domain setup' : 'Send from your own domain'}
            </LemonButton>
        </div>
    )
}
