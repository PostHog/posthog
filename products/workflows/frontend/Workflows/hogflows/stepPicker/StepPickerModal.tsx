import { useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { workflowLogic } from '../../workflowLogic'
import { CreateActionType } from '../hogFlowEditorLogic'
import { StepPicker } from './StepPicker'
import { StepPickerSurface } from './stepPickerPresentation'

const MODAL_MAX_WIDTH_PX = 1400

export function StepPickerModal({
    isOpen,
    onClose,
    surface,
    onPick,
}: {
    isOpen: boolean
    onClose: () => void
    surface: StepPickerSurface
    onPick: (action: CreateActionType) => void
}): JSX.Element {
    const { isRowScopedTrigger } = useValues(workflowLogic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            simple
            hideCloseButton
            width="92vw"
            maxWidth={MODAL_MAX_WIDTH_PX}
            contentRef={(dialog) => dialog?.setAttribute('aria-label', 'Add step')}
        >
            <div className="h-[88vh]">
                <StepPicker
                    surface={surface}
                    isRowScopedTrigger={isRowScopedTrigger}
                    onPick={(action) => {
                        onPick(action)
                        onClose()
                    }}
                />
            </div>
        </LemonModal>
    )
}
