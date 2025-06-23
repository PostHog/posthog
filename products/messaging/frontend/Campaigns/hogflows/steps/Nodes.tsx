import { IconPlus } from '@posthog/icons'
import { useUpdateNodeInternals } from '@xyflow/react'
import { useActions } from 'kea'
import { useEffect, useState } from 'react'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { getHogFlowStep } from './HogFlowSteps'
import { HogFlowStepNodeProps } from './types'

export type ReactFlowNodeType = HogFlowAction['type'] | 'dropzone'

export const REACT_FLOW_NODE_TYPES: Record<ReactFlowNodeType, React.ComponentType<HogFlowStepNodeProps>> = {
    dropzone: DropzoneNode,
    // Everything else is a HogFlowActionNode
    trigger: HogFlowActionNode,
    message: HogFlowActionNode,
    conditional_branch: HogFlowActionNode,
    delay: HogFlowActionNode,
    wait_until_condition: HogFlowActionNode,
    exit: HogFlowActionNode,
    random_cohort_branch: HogFlowActionNode,
    wait_until_time_window: HogFlowActionNode,
    function: HogFlowActionNode,
}

interface NodeProps {
    id: string
    children?: React.ReactNode
    icon?: React.ReactNode
    selected?: boolean
    type?: string
    data: HogFlowAction
}

function DropzoneNode({ id }: NodeProps): JSX.Element {
    const [isHighlighted, setIsHighlighted] = useState(false)
    const { setHighlightedDropzoneNodeId } = useActions(hogFlowEditorLogic)

    useEffect(() => {
        setHighlightedDropzoneNodeId(isHighlighted ? id : null)
    }, [isHighlighted, setHighlightedDropzoneNodeId])

    return (
        <div
            onDragOver={() => setIsHighlighted(true)}
            onDragLeave={() => setIsHighlighted(false)}
            className={`w-[100px] h-[34px] bg-surface-secondary border ${
                isHighlighted ? 'border-secondary bg-surface-primary' : 'border-primary'
            } border-dashed rounded p-2 cursor-pointer`}
        >
            <div className="flex gap-1 justify-center items-center">
                <IconPlus />
            </div>
        </div>
    )
}

function HogFlowActionNode(props: HogFlowStepNodeProps): JSX.Element | null {
    const updateNodeInternals = useUpdateNodeInternals()

    useEffect(() => {
        updateNodeInternals(props.id)
    }, [props.id, updateNodeInternals])

    const Step = getHogFlowStep(props.data.type)

    return (
        Step?.renderNode(props) || (
            <StepView name={`Error: ${props.data.type} not implemented`} selected={false} handles={[]} />
        )
    )
}
