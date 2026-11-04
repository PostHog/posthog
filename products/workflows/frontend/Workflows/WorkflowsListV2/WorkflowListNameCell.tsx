import { useValues } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { workflowSuggestionsAvailabilityLogic } from '../suggestions/workflowSuggestionsAvailabilityLogic'
import { WorkflowListRow } from './workflowListRows'

export function WorkflowListNameCell({ row }: { row: WorkflowListRow }): JSX.Element {
    const { suggestionsAvailable } = useValues(workflowSuggestionsAvailabilityLogic)
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
    const title = (
        <span className="flex items-center gap-2 flex-wrap min-w-0 w-full">
            {name}
            {suggestionsAvailable && row.workflow.status === 'active' && row.workflow.suggestions_enabled && (
                <LemonTag
                    type={row.workflow.pending_suggestions ? 'completion' : 'option'}
                    data-attr="workflow-list-suggestions"
                >
                    {!row.workflow.pending_suggestions
                        ? 'Self-driving'
                        : row.workflow.pending_suggestions === 1
                          ? '1 suggestion'
                          : `${row.workflow.pending_suggestions} suggestions`}
                </LemonTag>
            )}
        </span>
    )
    return (
        <LemonTableLink
            to={
                archived
                    ? undefined
                    : urls.workflow(
                          row.id,
                          row.workflow.status === 'active' && row.triggerType !== 'batch' ? 'overview' : 'workflow'
                      )
            }
            title={archived ? <Tooltip title="Restore this workflow to make changes">{name}</Tooltip> : title}
            description={description}
            truncateTitle
        />
    )
}
