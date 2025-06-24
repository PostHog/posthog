import clsx from 'clsx'
import { useValues } from 'kea'

import { NODE_HEIGHT, NODE_WIDTH } from '../../constants'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { HogFlowAction } from '../../types'
import { getHogFlowStep } from '../HogFlowSteps'

export function StepView({
    action,
    name,
    children,
}: {
    action: HogFlowAction
    name?: string
    children?: React.ReactNode
}): JSX.Element {
    const { selectedNode } = useValues(hogFlowEditorLogic)
    const isSelected = selectedNode?.id === action.id

    const Step = getHogFlowStep(action.type)

    return (
        <div
            className={clsx(
                'p-2 rounded border transition-all cursor-pointer bg-surface-primary',
                isSelected ? 'border-secondary bg-surface-secondary' : 'hover:bg-surface-secondary'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
            }}
        >
            <div className="flex gap-1 justify-center items-center">
                {Step?.icon}
                <div className="text-xs">{name ?? action.name}</div>
            </div>
            {children}
        </div>
    )
}
