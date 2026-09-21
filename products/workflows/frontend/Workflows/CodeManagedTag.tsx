import { IconCode } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { codeManagedReason, isCodeManagedWorkflow } from './codeManagedWorkflow'
import { HogFlow } from './hogflows/types'

/**
 * Marks a workflow a repository owns. Renders nothing for a workflow this app owns, so callers can
 * drop it in beside a name without branching.
 */
export function CodeManagedTag({ workflow }: { workflow: HogFlow | null | undefined }): JSX.Element | null {
    if (!isCodeManagedWorkflow(workflow)) {
        return null
    }

    return (
        <Tooltip title={codeManagedReason(workflow)}>
            <LemonTag type="default" icon={<IconCode />} data-attr="workflow-managed-by-code">
                Managed by code
            </LemonTag>
        </Tooltip>
    )
}
