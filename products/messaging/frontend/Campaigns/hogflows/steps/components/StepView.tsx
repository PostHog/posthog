import clsx from 'clsx'
import { useValues } from 'kea'

import { NODE_HEIGHT, NODE_WIDTH } from '../../constants'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { HogFlowAction } from '../../types'
import { getHogFlowStep } from '../HogFlowSteps'

export function StepView({ action, children }: { action: HogFlowAction; children?: React.ReactNode }): JSX.Element {
    const { selectedNode } = useValues(hogFlowEditorLogic)
    const isSelected = selectedNode?.id === action.id

    const Step = getHogFlowStep(action.type)

    return (
        <div
            className={clsx(
                'flex rounded border transition-all cursor-pointer bg-surface-primary',
                isSelected ? 'border-secondary bg-surface-secondary' : 'hover:bg-surface-secondary'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
            }}
        >
            <div className="flex gap-1 p-1 items-start">
                <div
                    className="flex justify-center h-6 items-center aspect-square rounded"
                    style={{ backgroundColor: `${Step?.color || '#6b7280'}20`, color: Step?.color || '#6b7280' }}
                >
                    {Step?.icon}
                </div>
                <div className="flex flex-col">
                    <div className="text-[0.5rem] font-semibold">{action.name}</div>
                    <div className="max-w-full text-[0.3rem]/1.5 text-muted text-ellipsis">{action.description}</div>
                </div>
            </div>
            {children}
        </div>
    )
}
