import type { HogFlowStateEnumApi } from 'products/workflows/frontend/generated/api.schemas'

export type WorkflowStatusValue = HogFlowStateEnumApi

export const WORKFLOW_STATUS_CONFIG: Record<
    WorkflowStatusValue,
    { label: string; type: 'success' | 'default' | 'muted' }
> = {
    active: { label: 'Active', type: 'success' },
    draft: { label: 'Draft', type: 'default' },
    archived: { label: 'Archived', type: 'muted' },
}
