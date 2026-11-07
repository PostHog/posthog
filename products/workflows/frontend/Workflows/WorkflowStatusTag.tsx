import { LemonTag } from '@posthog/lemon-ui'

import { WORKFLOW_STATUS_CONFIG, WorkflowStatusValue } from './workflowStatus'

export function WorkflowStatusTag({ status }: { status: string }): JSX.Element {
    const config = WORKFLOW_STATUS_CONFIG[status as WorkflowStatusValue] || WORKFLOW_STATUS_CONFIG.draft
    return <LemonTag type={config.type}>{config.label}</LemonTag>
}
