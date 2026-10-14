import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { StepPickerModal } from '../stepPicker/StepPickerModal'

export function HogFlowEditorPanelAddStep(): JSX.Element {
    const { newStepToPlace } = useValues(hogFlowEditorLogic)
    const { startPlacingNewStep, cancelPlacingNewStep } = useActions(hogFlowEditorLogic)
    const [pickerOpen, setPickerOpen] = useState(false)

    return (
        <div className="flex flex-col gap-2 overflow-y-auto p-3" data-attr="workflow-add-action">
            {newStepToPlace ? (
                <>
                    <div className="font-semibold truncate">{newStepToPlace.name}</div>
                    <p className="m-0 text-secondary">Click a highlighted spot in your workflow to add this step.</p>
                    <LemonButton
                        type="secondary"
                        className="self-start"
                        onClick={cancelPlacingNewStep}
                        data-attr="workflow-step-placement-cancel"
                    >
                        Cancel
                    </LemonButton>
                </>
            ) : (
                <>
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        className="self-start"
                        onClick={() => setPickerOpen(true)}
                        data-attr="workflow-step-picker-open"
                    >
                        Add step
                    </LemonButton>
                    <p className="m-0 text-secondary">Pick a step, then click where it goes in your workflow.</p>
                </>
            )}
            {pickerOpen && (
                <StepPickerModal
                    isOpen
                    onClose={() => setPickerOpen(false)}
                    surface="side_panel"
                    onPick={startPlacingNewStep}
                />
            )}
        </div>
    )
}
