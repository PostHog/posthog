import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { EmailSendingRateLimitPicker } from '../Workflows/hogflows/steps/components/EmailSendingRateLimitPicker'
import { broadcastSendingLogic } from './broadcastSendingLogic'
import { broadcastWizardLogic } from './broadcastWizardLogic'

export function BroadcastSendingRateModal(): JSX.Element {
    const { props } = useMountedLogic(broadcastWizardLogic)
    const logic = broadcastSendingLogic(props)
    const { sendingRateModalOpen, sendingRateDraft, savingSendingRate } = useValues(logic)
    const { closeSendingRateModal, setSendingRateDraft, saveSendingRate } = useActions(logic)

    return (
        <LemonModal
            isOpen={sendingRateModalOpen}
            onClose={closeSendingRateModal}
            title="Change the sending rate"
            description="Emails still waiting to send pick up the new rate the next time they try to send."
            width={560}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeSendingRateModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveSendingRate}
                        loading={savingSendingRate}
                        data-attr="broadcast-sending-rate-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <EmailSendingRateLimitPicker value={sendingRateDraft} onChange={setSendingRateDraft} />
        </LemonModal>
    )
}
