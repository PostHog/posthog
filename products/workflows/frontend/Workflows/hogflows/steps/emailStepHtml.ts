import type { HogFlowAction } from '../types'
import { isFunctionAction } from './types'

export function getEmailStepHtml(action: HogFlowAction): string | undefined {
    if (!isFunctionAction(action) || action.config.template_id !== 'template-email') {
        return undefined
    }
    const html: unknown = action.config.inputs?.email?.value?.html
    return typeof html === 'string' && html ? html : undefined
}
