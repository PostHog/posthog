import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconDecisionTree } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { getItemId } from '~/layout/panel-layout/ProjectTree/utils'

import { workflowSuggestionsAvailabilityLogic } from '../suggestions/workflowSuggestionsAvailabilityLogic'
import { WorkflowFolderPath } from './WorkflowFolderPath'
import { WorkflowFolderRow } from './WorkflowFolderRow'
import { workflowFoldersLogic } from './workflowFoldersLogic'
import { WorkflowListRow } from './workflowListRows'

export function WorkflowListNameCell({ row }: { row: WorkflowListRow }): JSX.Element {
    const { suggestionsAvailable } = useValues(workflowSuggestionsAvailabilityLogic)
    const { placements, pendingFileMoveIds } = useValues(workflowFoldersLogic)
    const { syncTypeAndRef } = useActions(projectTreeDataLogic)
    // A workflow with no file of its own never gets an entry, so asking again on every hover finds nothing new.
    const synced = useRef(false)
    const candidate = placements?.[`hog_flow::${row.id}`]
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
    const syncEntry = (): void => {
        if (!entry && canMove && !synced.current) {
            synced.current = true
            syncTypeAndRef('hog_flow', row.id)
        }
    }
    return (
        <WorkflowFolderRow
            icon={<IconDecisionTree />}
            drag={
                entry && canMove && !pendingFileMoveIds.includes(entry.id)
                    ? { id: getItemId(entry), label: `Drag workflow ${row.name}` }
                    : undefined
            }
            onMouseEnter={syncEntry}
            onFocus={syncEntry}
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
