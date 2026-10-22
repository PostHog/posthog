import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { customChartLogic } from './customChartLogic'

export function CustomChartChangeModal({ canvasId }: { canvasId: string }): JSX.Element {
    const logic = customChartLogic({ canvasId })
    const { changeModalOpen, changeMessage, refining, task } = useValues(logic)
    const { closeChangeModal, setChangeMessage, refine } = useActions(logic)
    const send = (): void => {
        if (changeMessage.trim() && !refining) {
            refine(changeMessage.trim())
        }
    }

    return (
        <LemonModal
            isOpen={changeModalOpen}
            onClose={refining ? undefined : closeChangeModal}
            title="Change the custom chart"
            description="Say what to change. The agent updates the chart, and the current chart shows until the new one is ready."
            width={560}
            hasUnsavedInput={!!changeMessage.trim()}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeChangeModal}
                        disabledReason={refining ? 'Sending' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={send}
                        loading={refining}
                        disabledReason={
                            !task ? 'Loading the chart' : changeMessage.trim() ? undefined : 'Describe the change first'
                        }
                        data-attr="custom-chart-change-send"
                    >
                        Update chart
                    </LemonButton>
                </>
            }
        >
            <LemonTextArea
                value={changeMessage}
                onChange={setChangeMessage}
                onPressCmdEnter={send}
                placeholder="For example: make the bars horizontal and label each one"
                minRows={3}
                maxRows={10}
                autoFocus
                disabled={refining}
                data-attr="custom-chart-change-message"
            />
        </LemonModal>
    )
}
