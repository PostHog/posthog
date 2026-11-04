import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'

import { LemonTree, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { convertFileSystemEntryToTreeDataItem } from '~/layout/panel-layout/ProjectTree/utils'

import { WORKFLOW_FILES_DRAG_SCOPE } from './workflowFolderDragScopes'
import { workflowFoldersLogic } from './workflowFoldersLogic'
import { WorkflowNewFolderButton } from './WorkflowNewFolderButton'

export function WorkflowFolderTree(): JSX.Element {
    const { folderPaths, folderCounts, browserReady, browserReadyLoading, currentFolder, expandedFolders } =
        useValues(workflowFoldersLogic)
    const { openFolder, selectTreeFolder, setExpandedFolders } = useActions(workflowFoldersLogic)
    const { savedItems } = useValues(projectTreeDataLogic)
    const folders = folderPaths.map(
        (path) => savedItems.find((entry) => entry.type === 'folder' && entry.path === path) ?? { path, type: 'folder' }
    )
    const children = convertFileSystemEntryToTreeDataItem({
        imports: folders,
        folderStates: Object.fromEntries(folderPaths.map((path) => [path, 'loaded'])),
        checkedItems: {},
        users: {},
        root: 'project://',
    })
    const foldersOnly = (items: TreeDataItem[]): TreeDataItem[] =>
        items
            .filter((item) => item.record?.type === 'folder')
            .map((item) => ({
                ...item,
                children: item.children ? foldersOnly(item.children) : undefined,
            }))
    return (
        <LemonTree
            data={[
                {
                    id: 'project://',
                    name: 'Project files',
                    record: { path: '', type: 'folder' },
                    children: foldersOnly(children),
                },
            ]}
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
            disableScroll
            enableDragAndDrop
            dragAndDropScope={WORKFLOW_FILES_DRAG_SCOPE}
            isItemDraggable={() => false}
            isItemDroppable={() => true}
        />
    )
}
