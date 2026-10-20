import type { CreateActionType } from '../../hogFlowEditorLogic'
import { useHogFlowStep } from '../../steps/HogFlowSteps'
import type { HogFlowAction } from '../../types'
import { tint } from './tileCanvasModel'

export function StepIcon({ step }: { step: CreateActionType }): JSX.Element {
    const look = useHogFlowStep(step as HogFlowAction)
    const color = look?.color ?? 'var(--color-text-secondary)'
    return (
        <span
            className="flex size-6 shrink-0 items-center justify-center rounded text-[14px]"
            style={{ color, backgroundColor: tint(color, 10) }}
        >
            {look?.icon}
        </span>
    )
}
