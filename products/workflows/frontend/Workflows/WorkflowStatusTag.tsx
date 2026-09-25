import { LemonTag } from '@posthog/lemon-ui'

const STATUS_CONFIG: Record<string, { label: string; type: 'success' | 'default' | 'muted' }> = {
    active: { label: 'Active', type: 'success' },
    draft: { label: 'Draft', type: 'default' },
    archived: { label: 'Archived', type: 'muted' },
}

export function WorkflowStatusTag({ status }: { status: string }): JSX.Element {
    const config = STATUS_CONFIG[status] || STATUS_CONFIG.draft
    return <LemonTag type={config.type}>{config.label}</LemonTag>
}
