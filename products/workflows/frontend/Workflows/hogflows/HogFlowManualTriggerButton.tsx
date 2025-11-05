import { useValues } from 'kea'
import { useState } from 'react'

import { IconButton } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { workflowLogic } from '../workflowLogic'
import { WorkflowSceneLogicProps } from '../workflowSceneLogic'

const VariableInputsPopover: React.FC = () => {
    const { workflow } = useValues(workflowLogic)

    return (
        <>
            {workflow?.variables?.map((variable) => (
                <div key={variable.key}>{variable.label}</div>
            ))}
        </>
    )
}

export const HogFlowManualTriggerButton = (props: WorkflowSceneLogicProps = {}): JSX.Element => {
    const logic = workflowLogic(props)
    const { workflow } = useValues(logic)
    const [manualTriggerPopoverVisible, setManualTriggerPopoverVisible] = useState(false)

    const triggerButton = (
        <LemonButton
            type="primary"
            disabledReason={workflow?.status !== 'active' && 'Must enable workflow to use trigger'}
            icon={<IconButton />}
            tooltip="Triggers workflow immediately"
            onClick={() => setManualTriggerPopoverVisible(true)}
        >
            Trigger
        </LemonButton>
    )

    return (
        <Popover
            visible={manualTriggerPopoverVisible}
            placement="bottom-start"
            onClickOutside={() => setManualTriggerPopoverVisible(false)}
            overlay={<VariableInputsPopover />}
        >
            {triggerButton}
        </Popover>
    )
}
