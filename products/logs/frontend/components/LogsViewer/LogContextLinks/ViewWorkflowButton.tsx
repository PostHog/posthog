import { useValues } from 'kea'

import { IconDecisionTree } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { workflowNameLogic } from 'products/workflows/frontend/Workflows/workflowNameLogic'

import type { LogContextLinksSurface } from './LogContextLinks'

export function ViewWorkflowButton({
    workflowId,
    surface,
}: {
    workflowId: string
    surface: LogContextLinksSurface
}): JSX.Element | null {
    // Batch run logs carry a run or batch job ID in log_source_id, which resolves to no workflow.
    const { workflow } = useValues(workflowNameLogic({ id: workflowId }))

    if (!workflow) {
        return null
    }

    return (
        <LemonButton
            to={urls.workflow(workflow.id, 'invocations')}
            icon={<IconDecisionTree />}
            size="xsmall"
            type="secondary"
            data-attr={`logs-${surface}-context-workflow`}
        >
            View workflow
        </LemonButton>
    )
}
