import { HogFlowAction } from '../types'
import { StepConditionalBranch } from './StepConditionalBranch'
import { StepDelay } from './StepDelay'
import { StepExit } from './StepExit'
import { StepMessage } from './StepMessage'
import { StepTrigger } from './StepTrigger'
import { StepWaitUntilCondition } from './StepWaitUntilCondition'
import { HogFlowStep } from './types'

export const HogFlowSteps: Partial<{
    [K in HogFlowAction['type']]: HogFlowStep<K>
}> = {
    trigger: StepTrigger,
    conditional_branch: StepConditionalBranch,
    exit: StepExit,
    delay: StepDelay,
    wait_until_condition: StepWaitUntilCondition,
    message: StepMessage,
} as const

// Type-safe accessor that preserves the key type
export function getHogFlowStep<T extends HogFlowAction['type']>(type: T): HogFlowStep<T> | undefined {
    return HogFlowSteps[type]
}
