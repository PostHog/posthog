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
            className={clsx('relative flex cursor-pointer transition-all hover:translate-y-[-2px]')}
            style={{
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
            }}
        >
            {/* Border layer - equivalent to ::before */}
            <div
                className="absolute -inset-px rounded pointer-events-none"
                style={{
                    border: `${isSelected ? '1px' : '0.5px'} solid var(--border)`,
                    zIndex: 0,
                }}
            />

            {/* Background and shadow layer - equivalent to ::after */}
            <div
                className={clsx('absolute rounded pointer-events-none bg-surface-primary hover:bg-surface-secondary')}
                style={{
                    inset: '-1px -1px 1px',
                    border: `${isSelected ? '1px' : '0.5px'} solid var(--border)`,
                    boxShadow: `0px 2px 0px 0px ${Step?.color ? `${Step.color}20` : 'var(--border-primary)'}`,
                    zIndex: 0,
                }}
            />

            {/* Content layer */}
            <div className="relative z-10 flex gap-1 p-1 items-start w-full">
                <div
                    className="flex justify-center h-6 items-center aspect-square rounded"
                    style={{
                        backgroundColor: Step?.color ? `${Step?.color}20` : 'var(--bg-surface-secondary)',
                        color: Step?.color || 'var(--text-secondary)',
                    }}
                >
                    {Step?.icon}
                </div>
                <div className="flex flex-col">
                    <div className="text-[0.45rem] font-sans font-medium">{action.name}</div>
                    <div className="max-w-full text-[0.3rem]/1.5 text-muted text-ellipsis">{action.description}</div>
                </div>
            </div>
            {children}
        </div>
    )
}
