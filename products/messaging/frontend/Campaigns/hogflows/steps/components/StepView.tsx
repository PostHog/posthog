import { useValues } from 'kea'
import { useMemo } from 'react'

import { NODE_HEIGHT, NODE_WIDTH } from '../../constants'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { HogFlowAction } from '../../types'
import { getHogFlowStep } from '../HogFlowSteps'
import { StepViewMetrics } from './StepViewMetrics'

export function StepView({ action }: { action: HogFlowAction }): JSX.Element {
    const { selectedNode, mode } = useValues(hogFlowEditorLogic)
    const isSelected = selectedNode?.id === action.id

    const height = mode === 'metrics' ? NODE_HEIGHT + 10 : NODE_HEIGHT

    const { selectedColor, colorLight, color, icon } = useMemo(() => {
        const Step = getHogFlowStep(action.type)

        return {
            selectedColor: Step?.color
                ? isSelected
                    ? `${Step?.color}`
                    : `${Step?.color}20`
                : isSelected
                  ? 'var(--border-primary)'
                  : 'var(--border)',
            colorLight: Step?.color ? `${Step?.color}20` : 'var(--border)',
            color: Step?.color || 'var(--text-secondary)',
            icon: Step?.icon,
        }
    }, [action.type, isSelected])

    return (
        <div
            className="relative flex flex-col cursor-pointer rounded user-select-none bg-surface-primary"
            style={{
                width: NODE_WIDTH,
                height,
                borderWidth: 1,
                borderColor: selectedColor,
                boxShadow: `0px 2px 0px 0px ${colorLight}`,
                zIndex: 0,
            }}
        >
            {/* Content layer */}
            <div className="relative z-10 flex gap-1 p-1 items-start w-full">
                <div
                    className="flex justify-center h-6 items-center aspect-square rounded"
                    style={{
                        backgroundColor: colorLight,
                        color,
                    }}
                >
                    {icon}
                </div>
                <div className="flex flex-col">
                    <div className="flex justify-between items-center gap-1">
                        <div className="text-[0.45rem] font-sans font-medium">{action.name}</div>
                    </div>

                    <div className="max-w-full text-[0.3rem]/1.5 text-muted text-ellipsis">{action.description}</div>
                </div>
            </div>
            {mode === 'metrics' && (
                <div
                    style={{
                        borderTopColor: colorLight,
                        borderTopWidth: 1,
                    }}
                >
                    <StepViewMetrics action={action} />
                </div>
            )}
        </div>
    )
}
