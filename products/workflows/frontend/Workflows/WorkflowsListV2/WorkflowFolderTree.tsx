import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'

import { LemonTree, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { convertFileSystemEntryToTreeDataItem } from '~/layout/panel-layout/ProjectTree/utils'

import { workflowFoldersLogic } from './workflowFoldersLogic'

export function WorkflowFolderTree(): JSX.Element {
    const {
        folderPaths,
        folderTreeEntries,
        folderCounts,
        browserReady,
        browserReadyLoading,
        currentFolder,
        expandedFolders,
    } = useValues(workflowFoldersLogic)
    const { openFolder, selectTreeFolder, setExpandedFolders } = useActions(workflowFoldersLogic)
    const children = convertFileSystemEntryToTreeDataItem({
        imports: folderTreeEntries,
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
            defaultNodeIcon={<IconFolder />}
            disableScroll
        />
    )
}
