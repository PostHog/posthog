import { HogFlowAction } from '../types'
import { StepConditionalBranch } from './StepConditionalBranch'
import { StepExit } from './StepExit'
import { StepTrigger } from './StepTrigger'
import { HogFlowStep } from './types'

export const HogFlowSteps: Partial<{
    [K in HogFlowAction['type']]: HogFlowStep<K>
}> = {
    trigger: StepTrigger,
    conditional_branch: StepConditionalBranch,
    exit: StepExit,
} as const

// Type-safe accessor that preserves the key type
export function getHogFlowStep<T extends HogFlowAction['type']>(type: T): HogFlowStep<T> | undefined {
    return HogFlowSteps[type]
}
