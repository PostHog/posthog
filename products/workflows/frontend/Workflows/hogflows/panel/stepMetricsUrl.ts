import { urls } from 'scenes/urls'

import { EXIT_NODE_ID, TRIGGER_NODE_ID } from '../../workflowLogic'
import type { HogFlow } from '../types'

/** The metrics tab can drill into a single step, but trigger and exit only exist in its workflow totals. */
export function getStepMetricsUrl(workflow: HogFlow, actionId: string): string | null {
    if (
        !workflow.id ||
        workflow.id === 'new' ||
        workflow.trigger?.type === 'batch' ||
        [TRIGGER_NODE_ID, EXIT_NODE_ID].includes(actionId)
    ) {
        return null
    }
    return `${urls.workflow(workflow.id, 'metrics')}?action=${encodeURIComponent(actionId)}`
}
