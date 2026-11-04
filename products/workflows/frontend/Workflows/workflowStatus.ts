export type WorkflowStatusValue = 'draft' | 'active' | 'archived'

export const WORKFLOW_STATUS_CONFIG: Record<
    WorkflowStatusValue,
    { label: string; type: 'success' | 'default' | 'muted' }
> = {
    active: { label: 'Active', type: 'success' },
    draft: { label: 'Draft', type: 'default' },
    archived: { label: 'Archived', type: 'muted' },
}
