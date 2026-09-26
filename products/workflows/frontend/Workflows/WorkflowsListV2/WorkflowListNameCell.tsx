import { IconDecisionTree, IconLetter } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { WorkflowListRow } from './workflowListRows'

function rowUrl(row: WorkflowListRow): string {
    return row.kind === 'workflow' ? urls.workflow(row.id, 'workflow') : urls.workflowsLibraryTemplate(row.id)
}

/** The kind icon and the linked name, with the description in a tooltip. */
export function WorkflowListNameCell({ row }: { row: WorkflowListRow }): JSX.Element {
    const description = row.kind === 'workflow' ? row.workflow.description : row.template.description
    const name = row.name || 'Untitled'
    return (
        <div className="flex items-center gap-2 min-w-0">
            {row.kind === 'workflow' ? (
                <IconDecisionTree className="shrink-0 text-secondary" />
            ) : (
                <IconLetter className="shrink-0 text-secondary" />
            )}
            {row.kind === 'workflow' && row.workflow.status === 'archived' ? (
                <Tooltip title="Restore this workflow to make changes">
                    <span data-attr="workflows-list-v2-name" className="font-semibold text-muted truncate">
                        {name}
                    </span>
                </Tooltip>
            ) : (
                <Tooltip title={description || undefined}>
                    <Link to={rowUrl(row)} data-attr="workflows-list-v2-name" className="font-semibold truncate">
                        {name}
                    </Link>
                </Tooltip>
            )}
        </div>
    )
}
