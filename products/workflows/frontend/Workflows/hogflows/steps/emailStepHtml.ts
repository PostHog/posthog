import type { HogFlowAction } from '../types'
import { isEmailAction } from './types'

export function getEmailStepHtml(action: HogFlowAction): string | undefined {
    return isEmailAction(action) ? action.config.inputs?.email?.value?.html || undefined : undefined
}

export function hasEmailPreview(action: HogFlowAction): boolean {
    return !!getEmailStepHtml(action)
}
