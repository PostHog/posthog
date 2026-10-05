import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { FirstRunReach, firstRunReachLogic } from './firstRunReachLogic'

function ownDomainSetupUrl(): string {
    return urls.workflows('channels')
}

function reachedMembers({ counts }: FirstRunReach): string {
    return counts && counts.reached > 0
        ? `your organization's ${pluralize(counts.reached, 'verified member')}`
        : 'verified members of your organization'
}

function peopleNotReachedYet({ counts }: FirstRunReach): string {
    return counts && counts.notReachedYet > 0
        ? `the ${pluralize(counts.notReachedYet, 'person', 'people')} in this project with an email address`
        : 'the people in this project'
}

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1)
}

export function FirstRunReachLine({ senderIntegrationId }: { senderIntegrationId: number | null }): JSX.Element | null {
    const { reach } = useValues(firstRunReachLogic({ senderIntegrationId }))

    if (!reach) {
        return null
    }

    return (
        <div className="flex flex-col gap-2 items-start font-normal" data-attr="workflows-first-run-reach">
            <span>
                Sends from <strong translate="no">{reach.senderAddress}</strong> only to {reachedMembers(reach)}.{' '}
                {reach.ownDomain === 'verifying'
                    ? `Your domain is not verified yet. Once it is, ${peopleNotReachedYet(reach)} can get these emails too.`
                    : `${capitalize(peopleNotReachedYet(reach))} can get these emails once you send from your own domain.`}
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
