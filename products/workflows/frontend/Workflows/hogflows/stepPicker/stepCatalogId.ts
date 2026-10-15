import type { HogFlowAction } from '../types'

type StepIdentity = Pick<HogFlowAction, 'type' | 'config'>

export function templateIdOf(action: StepIdentity): string | null {
    return 'template_id' in action.config && typeof action.config.template_id === 'string'
        ? action.config.template_id
        : null
}

export function stepCatalogIdOf(action: StepIdentity): string {
    return templateIdOf(action) ?? `step-${action.type}`
}
