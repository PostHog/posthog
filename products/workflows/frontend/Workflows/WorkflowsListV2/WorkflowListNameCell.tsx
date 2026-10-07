import { Tooltip } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { WorkflowListRow } from './workflowListRows'

export function WorkflowListNameCell({ row }: { row: WorkflowListRow }): JSX.Element {
    const archived = row.workflow.status === 'archived'
    const name = (
        <span data-attr="workflows-list-v2-name" className={archived ? 'truncate text-muted' : 'truncate'}>
            {row.name || 'Untitled'}
        </span>
    )
    const description = row.workflow.description ? (
        <Tooltip title={row.workflow.description}>
            <span data-attr="workflows-list-v2-description" className="block truncate">
                {row.workflow.description}
            </span>
        </Tooltip>
    ) : undefined
    return (
        <LemonTableLink
            to={archived ? undefined : urls.workflow(row.id, 'workflow')}
            title={archived ? <Tooltip title="Restore this workflow to make changes">{name}</Tooltip> : name}
            description={description}
            truncateTitle
        />
    )
}
