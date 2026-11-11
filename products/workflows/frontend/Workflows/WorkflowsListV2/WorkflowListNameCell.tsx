import { useActions, useValues } from 'kea'

import { IconDecisionTree } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { getItemId } from '~/layout/panel-layout/ProjectTree/utils'

import { workflowSuggestionsAvailabilityLogic } from '../suggestions/workflowSuggestionsAvailabilityLogic'
import { WorkflowFolderPath } from './WorkflowFolderPath'
import { WorkflowFolderRow } from './WorkflowFolderRow'
import { WorkflowListRow } from './workflowListRows'
import { workflowsListV2Logic } from './workflowsListV2Logic'

export function WorkflowListNameCell({ row }: { row: WorkflowListRow }): JSX.Element {
    const { suggestionsAvailable } = useValues(workflowSuggestionsAvailabilityLogic)
    const { filesByRef } = useValues(workflowsListV2Logic)
    const { syncTypeAndRef } = useActions(projectTreeDataLogic)
    const candidate = filesByRef[`hog_flow::${row.id}`]
    const entry = candidate?.shortcut ? undefined : candidate
    const canMove = !['viewer', 'none'].includes(row.workflow.user_access_level ?? '')
    const archived = row.workflow.status === 'archived'
    const workflowUrl = urls.workflow(
        row.id,
        row.workflow.status === 'active' && row.triggerType !== 'batch' ? 'overview' : 'workflow'
    )
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
        <WorkflowFolderRow
            icon={<IconDecisionTree />}
            drag={entry && canMove ? { id: getItemId(entry), label: `Drag workflow ${row.name}` } : undefined}
            onMouseEnter={() => !entry && canMove && syncTypeAndRef('hog_flow', row.id)}
            onFocus={() => !entry && canMove && syncTypeAndRef('hog_flow', row.id)}
        >
            {entry && <WorkflowFolderPath path={entry.path} />}
            <LemonTableLink
                to={archived ? undefined : workflowUrl}
                title={archived ? <Tooltip title="Restore this workflow to make changes">{name}</Tooltip> : title}
                description={description}
                truncateTitle
            />
        </WorkflowFolderRow>
    )
}
