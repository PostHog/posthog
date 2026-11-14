import type { HogFlow } from './hogflows/types'

export type WorkflowTriggerTypeFilter = 'all' | (NonNullable<HogFlow['trigger']> extends { type: infer T } ? T : never)

// Keep in sync with TRIGGER_TYPES in products/workflows/backend/models/hog_flow/hog_flow.py.
export const WORKFLOW_TRIGGER_TYPE_OPTIONS: { value: WorkflowTriggerTypeFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'event', label: 'Event' },
    { value: 'schedule', label: 'Schedule' },
    { value: 'manual', label: 'Manual' },
    { value: 'batch', label: 'Batch' },
    { value: 'webhook', label: 'Webhook' },
    { value: 'tracking_pixel', label: 'Tracking pixel' },
    { value: 'data-warehouse-table', label: 'Data warehouse table' },
    { value: 'data-warehouse-view', label: 'Data warehouse view' },
    { value: 'internal-event', label: 'Internal event' },
]
