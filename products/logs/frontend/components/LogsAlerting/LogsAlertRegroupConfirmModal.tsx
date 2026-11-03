import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { logsAlertFormLogic } from './logsAlertFormLogic'

export function LogsAlertRegroupConfirmModal(): JSX.Element {
    const { isRegroupConfirmationOpen, regroupConfirmation } = useValues(logsAlertFormLogic)
    const { closeRegroupConfirmation, confirmRegroup } = useActions(logsAlertFormLogic)

    return (
        <LemonModal
            isOpen={isRegroupConfirmationOpen}
            onClose={closeRegroupConfirmation}
            title="Change how this alert groups?"
            maxWidth="32rem"
            footer={
                <div className="flex flex-wrap justify-end gap-2">
                    <LemonButton type="secondary" onClick={closeRegroupConfirmation}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={confirmRegroup} data-attr="logs-alert-regroup-confirm">
                        Save and reset
                    </LemonButton>
                </div>
            }
        >
            <p className="m-0">{regroupConfirmation}</p>
        </LemonModal>
    )
}
