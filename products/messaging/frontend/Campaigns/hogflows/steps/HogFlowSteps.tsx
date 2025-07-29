import { HogFlowAction } from '../types'
import { StepConditionalBranch } from './StepConditionalBranch'
import { StepDelay } from './StepDelay'
import { StepExit } from './StepExit'
import { StepFunctionEmail } from './StepFunctionEmail'
import { StepFunctionSlack } from './StepFunctionSlack'
import { StepFunctionSms } from './StepFunctionSms'
import { StepFunctionWebhook } from './StepFunctionWebhook'
import { StepRandomCohortBranch } from './StepRandomCohortBranch'
import { StepTrigger } from './StepTrigger'
import { StepWaitUntilCondition } from './StepWaitUntilCondition'
import { StepWaitUntilTimeWindow } from './StepWaitUntilTimeWindow'
import { HogFlowStep } from './types'

export const HogFlowSteps: Partial<{
    [K in HogFlowAction['type']]: HogFlowStep<K>
}> = {
    trigger: StepTrigger,
    conditional_branch: StepConditionalBranch,
    exit: StepExit,
    delay: StepDelay,
    wait_until_condition: StepWaitUntilCondition,
    wait_until_time_window: StepWaitUntilTimeWindow,
    random_cohort_branch: StepRandomCohortBranch,
    function_email: StepFunctionEmail,
    function_webhook: StepFunctionWebhook,
    function_sms: StepFunctionSms,
    function_slack: StepFunctionSlack,
    // function: StepFunction,
} as const

// Type-safe accessor that preserves the key type
export function getHogFlowStep<T extends HogFlowAction['type']>(type: T): HogFlowStep<T> | undefined {
    return HogFlowSteps[type]
}
