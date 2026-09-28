import { Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { WorkflowListRow } from './workflowListRows'

export function WorkflowListNameCell({ row }: { row: WorkflowListRow }): JSX.Element {
    const name = row.name || 'Untitled'
    if (row.workflow.status === 'archived') {
        return (
            <Tooltip title="Restore this workflow to make changes">
                <span data-attr="workflows-list-v2-name" className="block font-semibold text-muted truncate">
                    {name}
                </span>
            </Tooltip>
        )
    }
    return (
        <Tooltip title={row.workflow.description || undefined}>
            <Link
                to={urls.workflow(row.id, 'workflow')}
                data-attr="workflows-list-v2-name"
                className="block font-semibold truncate"
            >
                {name}
            </Link>
        </Tooltip>
    )
}
