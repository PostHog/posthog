import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { broadcastSendingLogic } from './broadcastSendingLogic'
import { broadcastWizardLogic } from './broadcastWizardLogic'

export function BroadcastStillToSend(): JSX.Element {
    const { props } = useMountedLogic(broadcastWizardLogic)
    const logic = broadcastSendingLogic(props)
    const { stillToSend, stillToSendDuration, inFlightLoading, inFlightFailed } = useValues(logic)
    const { loadInFlight } = useActions(logic)

    if (inFlightLoading && stillToSend === null) {
        return <LemonSkeleton className="h-5 w-24" />
    }
    if (inFlightFailed || stillToSend === null) {
        return (
            <span className="flex flex-wrap items-center gap-2 text-muted">
                Couldn't count what's left.
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={loadInFlight}
                    loading={inFlightLoading}
                    data-attr="broadcast-still-to-send-retry"
                >
                    Try again
                </LemonButton>
            </span>
        )
    }
    if (stillToSend === 0) {
        return <span className="text-muted">Nothing waiting to send</span>
    }
    return (
        <div className="flex flex-col gap-0.5" data-attr="broadcast-still-to-send">
            <span>{`${humanFriendlyNumber(stillToSend)} ${stillToSend === 1 ? 'person' : 'people'}`}</span>
            {stillToSendDuration ? (
                <span className="text-xs text-muted">{`About ${stillToSendDuration} left at this rate`}</span>
            ) : null}
        </div>
    )
}
