import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TreeNodeDroppable } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { addProductIntent } from 'lib/utils/product-intents'

import { splitPath, joinPath } from '~/layout/panel-layout/ProjectTree/utils'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { newWorkflowLogic } from '../newWorkflowLogic'
import { workflowTemplatesLogic } from '../templates/workflowTemplatesLogic'
import { workflowsLogic } from '../workflowsLogic'
import { templateTypeForListType } from '../workflowTypeFilters'
import { WORKFLOW_FOLDER_BREADCRUMBS_DROP_SCOPE } from './workflowFolderDragScopes'
import { workflowFoldersLogic } from './workflowFoldersLogic'
import { WorkflowNewFolderButton } from './WorkflowNewFolderButton'
import { WorkflowsListV2ColumnsMenu } from './WorkflowsListV2ColumnsMenu'

export function WorkflowFolderToolbar(): JSX.Element {
    const {
        currentFolder,
        folderJumpPaths,
        folderJumpSearch,
        folderCounts,
        folderRows,
        folderTemplates,
        childFolders,
        hasActiveQuery,
        browserReady,
    } = useValues(workflowFoldersLogic)
    const { openFolder, setFolderJumpSearch } = useActions(workflowFoldersLogic)
    const { filters } = useValues(workflowsLogic)
    const { setTypeFilter } = useActions(workflowTemplatesLogic)
    const { startNewWorkflow } = useActions(newWorkflowLogic)
    const { selectedFiles } = useValues(workflowFoldersLogic)
    const { moveSelectedFiles, clearSelectedFiles } = useActions(workflowFoldersLogic)
    const segments = splitPath(currentFolder ?? '')
    const count = folderRows.length + folderTemplates.length
    return (
        <>
            {selectedFiles.length > 0 && (
                <div
                    className="flex flex-wrap gap-2 items-center border rounded px-2 py-1 mb-2 bg-surface-secondary"
                    data-attr="workflows-folder-bulk-move"
                >
                    <span translate="no">{`${selectedFiles.length} ${selectedFiles.length === 1 ? 'item' : 'items'} selected`}</span>
                    <LemonButton size="small" type="secondary" onClick={moveSelectedFiles}>
                        Move to…
                    </LemonButton>
                    <LemonButton size="small" onClick={clearSelectedFiles}>
                        Clear selection
                    </LemonButton>
                </div>
            )}
            <div
                className="flex flex-wrap gap-x-3 gap-y-1 items-center min-h-8 mb-1"
                data-attr="workflows-folder-toolbar"
            >
                <div className="flex flex-wrap gap-1 items-center min-w-0 text-sm">
                    <span className="@min-[48rem]/main-content:hidden">
                        <LemonMenu
                            onVisibilityChange={() => setFolderJumpSearch('')}
                            items={[
                                {
                                    label: () => (
                                        <LemonInput
                                            size="small"
                                            placeholder="Find a folder"
                                            value={folderJumpSearch}
                                            onChange={setFolderJumpSearch}
                                            autoFocus
                                            onPressEnter={() =>
                                                folderJumpPaths.length && openFolder(folderJumpPaths[0] || null)
                                            }
                                        />
                                    ),
                                },
                                ...folderJumpPaths.map((path) => ({
                                    label: (
                                        <span
                                            className="flex gap-2 justify-between min-w-0 w-full"
                                            style={{ paddingLeft: Math.max(0, splitPath(path).length - 1) * 12 }}
                                        >
                                            <span className="truncate">
                                                {splitPath(path).at(-1) || 'Project files'}
                                            </span>
                                            <span
                                                className="text-secondary text-xs tabular-nums"
                                                translate="no"
                                            >{`(${folderCounts[path] ?? 0})`}</span>
                                        </span>
                                    ),
                                    active: path === (currentFolder ?? ''),
                                    onClick: () => openFolder(path || null),
                                })),
                                ...(folderJumpPaths.length
                                    ? []
                                    : [{ label: 'No folders match', disabledReason: 'Try another folder name' }]),
                            ]}
                        >
                            <LemonButton size="xsmall" type="secondary" icon={<IconFolder />}>
                                Folders
                            </LemonButton>
                        </LemonMenu>
                    </span>
                    <TreeNodeDroppable id="project://" scope={WORKFLOW_FOLDER_BREADCRUMBS_DROP_SCOPE} isDroppable>
                        <LemonButton size="xsmall" onClick={() => openFolder(null)} active={!currentFolder}>
                            Project files
                        </LemonButton>
                    </TreeNodeDroppable>
                    {segments.map((segment, index) => (
                        <span key={index} className="flex items-center gap-1 min-w-0">
                            <span className="text-secondary">/</span>
                            <TreeNodeDroppable
                                id={`project://${joinPath(segments.slice(0, index + 1))}`}
                                scope={WORKFLOW_FOLDER_BREADCRUMBS_DROP_SCOPE}
                                isDroppable
                            >
                                <LemonButton
                                    size="xsmall"
                                    active={index === segments.length - 1}
                                    onClick={() => openFolder(joinPath(segments.slice(0, index + 1)))}
                                >
                                    {segment}
                                </LemonButton>
                            </TreeNodeDroppable>
                        </span>
                    ))}
                    {browserReady && (
                        <span className="text-secondary text-xs ml-1" translate="no">
                            {!hasActiveQuery && count === 0 && childFolders.length > 0
                                ? `${childFolders.length} folders`
                                : `${count} items${hasActiveQuery && currentFolder ? ' match, subfolders included' : ''}`}
                        </span>
                    )}
                    <WorkflowNewFolderButton parent={currentFolder ?? ''} />
                </div>
                <div className="flex gap-2 ml-auto">
                    <WorkflowsListV2ColumnsMenu />
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Workflow}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => {
                                void addProductIntent({
                                    product_type: ProductKey.WORKFLOWS,
                                    intent_context: ProductIntentContext.WORKFLOW_CREATED,
                                })
                                setTypeFilter(templateTypeForListType(filters.type))
                                startNewWorkflow()
                            }}
                            tooltip={`The workflow lands in ${currentFolder && currentFolder !== 'Unfiled' ? currentFolder.replaceAll('/', ' / ') : 'Unfiled / Workflows'}`}
                            data-attr="new-workflow"
                        >
                            New workflow
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </div>
        </>
    )
}
