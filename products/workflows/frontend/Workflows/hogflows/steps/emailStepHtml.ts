import type { HogFlowAction } from '../types'
import { isFunctionAction } from './types'

export function getEmailStepHtml(action: HogFlowAction): string | undefined {
    const usesEmailTemplate = isFunctionAction(action) && action.config.template_id === 'template-email'
    return usesEmailTemplate ? action.config.inputs?.email?.value?.html || undefined : undefined
}
