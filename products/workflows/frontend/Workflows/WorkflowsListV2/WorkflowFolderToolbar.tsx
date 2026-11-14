import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { TreeNodeDroppable } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { pluralize } from 'lib/utils/strings'

import { splitPath, joinPath } from '~/layout/panel-layout/ProjectTree/utils'

import { WORKFLOW_FOLDER_BREADCRUMBS_DROP_SCOPE } from './workflowFolderDragScopes'
import { workflowFoldersLogic } from './workflowFoldersLogic'
import { WorkflowNewFolderButton } from './WorkflowNewFolderButton'
import { WorkflowNewWorkflowButton } from './WorkflowNewWorkflowButton'
import { WorkflowsListV2ColumnsMenu } from './WorkflowsListV2ColumnsMenu'
import { workflowsListV2Logic } from './workflowsListV2Logic'

// The menu mounts every item it gets, so a large project lists the first matches and asks for a narrower search.
const SHOWN_FOLDER_MATCHES = 50

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
    // Counts come from the loaded workflows, so before the list arrives every folder would read 0.
    const { listLoaded } = useValues(workflowsListV2Logic)
    const { openFolder, setFolderJumpSearch } = useActions(workflowFoldersLogic)
    const segments = splitPath(currentFolder ?? '')
    const count = folderRows.length + folderTemplates.length
    return (
        <div className="flex flex-wrap gap-x-3 gap-y-1 items-center min-h-8 mb-1" data-attr="workflows-folder-toolbar">
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
                            ...folderJumpPaths.slice(0, SHOWN_FOLDER_MATCHES).map((path) => ({
                                label: (
                                    <span
                                        className="flex gap-2 justify-between min-w-0 w-full"
                                        style={{ paddingLeft: Math.max(0, splitPath(path).length - 1) * 12 }}
                                    >
                                        <span className="truncate">{splitPath(path).at(-1) || 'Project files'}</span>
                                        <span className="text-secondary text-xs tabular-nums" translate="no">
                                            {listLoaded ? `(${folderCounts[path] ?? 0})` : '…'}
                                        </span>
                                    </span>
                                ),
                                active: path === (currentFolder ?? ''),
                                onClick: () => openFolder(path || null),
                            })),
                            ...(folderJumpPaths.length > SHOWN_FOLDER_MATCHES
                                ? [
                                      {
                                          label: () => (
                                              <span className="block text-secondary text-xs px-2 py-1">
                                                  {`Type to narrow down ${pluralize(folderJumpPaths.length - SHOWN_FOLDER_MATCHES, 'more folder')}`}
                                              </span>
                                          ),
                                      },
                                  ]
                                : []),
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
                {browserReady && listLoaded && (
                    <span className="text-secondary text-xs ml-1" translate="no">
                        {!hasActiveQuery && count === 0 && childFolders.length > 0
                            ? pluralize(childFolders.length, 'folder')
                            : hasActiveQuery && currentFolder
                              ? `${pluralize(count, 'item')} ${count === 1 ? 'matches' : 'match'}, subfolders included`
                              : pluralize(count, 'item')}
                    </span>
                )}
                <WorkflowNewFolderButton parent={currentFolder ?? ''} />
            </div>
            <div className="flex gap-2 ml-auto">
                <WorkflowsListV2ColumnsMenu />
                <WorkflowNewWorkflowButton />
            </div>
        </div>
    )
}
