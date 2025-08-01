import { LemonModal, LemonButton } from '@posthog/lemon-ui'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { useActions, useValues } from 'kea'

import { llmObservabilityTraceLogic, DisplayOption } from '../llmObservabilityTraceLogic'

export function DisplayOptionsModal(): JSX.Element {
    const { displayOptionsModalVisible, displayOption } = useValues(llmObservabilityTraceLogic)
    const { hideDisplayOptionsModal, setDisplayOption } = useActions(llmObservabilityTraceLogic)

    const displayOptions: LemonRadioOption<DisplayOption>[] = [
        {
            value: DisplayOption.ExpandAll,
            label: 'Expand all messages by default',
        },
        {
            value: DisplayOption.CollapseExceptOutputAndLastInput,
            label: 'Collapse all messages by default, except for the last input message and all output messages',
        },
    ]

    return (
        <LemonModal
            isOpen={displayOptionsModalVisible}
            title="Display Options"
            onClose={hideDisplayOptionsModal}
            footer={
                <LemonButton type="primary" onClick={hideDisplayOptionsModal}>
                    Done
                </LemonButton>
            }
        >
            <div className="space-y-4">
                <p className="text-muted">Choose how conversation messages should be displayed by default:</p>
                <LemonRadio value={displayOption} onChange={setDisplayOption} options={displayOptions} />
            </div>
        </LemonModal>
    )
}
