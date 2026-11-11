import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { manageDisabledReason } from './broadcastLifecycle'
import { broadcastSendingLogic } from './broadcastSendingLogic'
import { broadcastWizardLogic } from './broadcastWizardLogic'

export function BroadcastSendingRate(): JSX.Element {
    const { props } = useMountedLogic(broadcastWizardLogic)
    const logic = broadcastSendingLogic(props)
    const { broadcast, sendingRate } = useValues(logic)
    const { openSendingRateModal } = useActions(logic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <span>
                {sendingRate
                    ? `At most ${humanFriendlyNumber(sendingRate.count)} emails per ${sendingRate.period}`
                    : 'No limit'}
            </span>
            {broadcast?.status !== 'archived' ? (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={openSendingRateModal}
                    disabledReason={manageDisabledReason(broadcast?.user_access_level)}
                    data-attr="broadcast-sending-rate-edit"
                >
                    Change
                </LemonButton>
            ) : null}
        </div>
    )
}
