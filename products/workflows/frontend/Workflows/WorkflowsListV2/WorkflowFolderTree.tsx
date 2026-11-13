import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'

import { LemonTree } from 'lib/lemon-ui/LemonTree/LemonTree'

import { WORKFLOW_FILES_DRAG_SCOPE } from './workflowFolderDragScopes'
import { workflowFoldersLogic } from './workflowFoldersLogic'
import { WorkflowNewFolderButton } from './WorkflowNewFolderButton'

export function WorkflowFolderTree(): JSX.Element {
    const { folderTree, folderCounts, browserReady, browserReadyLoading, currentFolder, expandedFolders } =
        useValues(workflowFoldersLogic)
    const { openFolder, selectTreeFolder, setExpandedFolders } = useActions(workflowFoldersLogic)
    return (
        <LemonTree
            data={folderTree}
            expandedItemIds={expandedFolders}
            onSetExpandedItemIds={setExpandedFolders}
            isItemActive={(item) => (item.record?.path ?? '') === (currentFolder ?? '')}
            onItemClick={(item) => openFolder(item?.record?.path || null)}
            onFolderClick={(item, isExpanded) => selectTreeFolder(item?.record?.path || null, isExpanded)}
            renderItem={(item) => (
                <span className="flex items-center gap-1 min-w-0">
                    <span className="truncate">{item.name}</span>
                    <span className="text-secondary text-xs tabular-nums" translate="no">
                        {browserReady && !browserReadyLoading ? `(${folderCounts[item.record?.path ?? ''] ?? 0})` : '…'}
                    </span>
                </span>
            )}
            itemSideAction={() => null}
            itemSideActionButton={(item) => (
                <span className="opacity-0 group-hover/lemon-tree-button-group:opacity-100 focus-within:opacity-100">
                    <WorkflowNewFolderButton parent={item.record?.path ?? ''} iconOnly />
                </span>
            )}
            defaultNodeIcon={<IconFolder />}
            virtualized
            enableDragAndDrop
            dragAndDropScope={WORKFLOW_FILES_DRAG_SCOPE}
            isItemDraggable={() => false}
            isItemDroppable={() => true}
        />
    )
}
