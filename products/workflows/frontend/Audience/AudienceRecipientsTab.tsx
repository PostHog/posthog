import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'

import { AudienceRecipients } from './AudienceRecipients'
import { audienceSceneLogic } from './audienceSceneLogic'
import { recipientsLogic } from './recipientsLogic'
import { AudienceSetup } from './setup/AudienceSetup'
import { UnreachablePersonsNotice } from './UnreachablePersonsNotice'

function SetupDecisionSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="audience-recipients-first-load">
            <LemonSkeleton className="h-8 max-w-100" />
            <LemonSkeleton repeat={5} className="h-10" />
        </div>
    )
}

export function AudienceRecipientsTab(): JSX.Element {
    const { setupPageOpen } = useValues(audienceSceneLogic)
    const { accessDenied, showsSetup, setupDecisionPending } = useValues(recipientsLogic)

    if (accessDenied) {
        return <AccessDenied reason="You need viewer access to Workflows to see recipients." inline />
    }
    if (setupPageOpen || showsSetup) {
        return (
            <div className="flex flex-col gap-3 min-w-0">
                <UnreachablePersonsNotice />
                <AudienceSetup />
            </div>
        )
    }
    if (setupDecisionPending) {
        return <SetupDecisionSkeleton />
    }
    return <AudienceRecipients />
}
