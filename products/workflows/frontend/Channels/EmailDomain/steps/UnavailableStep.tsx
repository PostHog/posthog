import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { BigAction } from '../components/BigAction'
import { StepHeading } from '../components/StepHeading'
import { emailDomainLogic } from '../emailDomainLogic'
import { HedgehogPanic } from '../hoggies'

export function UnavailableStep(): JSX.Element {
    const { senderLoading, senderMissing, statusLoading } = useValues(emailDomainLogic)
    const { retry } = useActions(emailDomainLogic)
    const retrying = senderLoading || statusLoading
    if (senderMissing) {
        return (
            <StepHeading
                Hoggie={HedgehogPanic}
                title="This sending domain no longer exists"
                lead="It may have been removed. Go back to Channels to set it up again."
            />
        )
    }
    return (
        <div className="flex flex-col gap-8">
            <StepHeading
                Hoggie={HedgehogPanic}
                title="We could not load your sending domain"
                lead="Something went wrong while checking it. Try again, and if it keeps happening contact support."
            />
            <BigAction
                icon={<IconRefresh />}
                onClick={retry}
                loading={retrying}
                disabledReason={retrying ? 'Loading' : undefined}
                data-attr="email-domain-retry"
            >
                Try again
            </BigAction>
        </div>
    )
}
