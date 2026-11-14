import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'

import { LemonTree } from 'lib/lemon-ui/LemonTree/LemonTree'

import { workflowFoldersLogic } from './workflowFoldersLogic'
import { workflowsListV2Logic } from './workflowsListV2Logic'

export function WorkflowFolderTree(): JSX.Element {
    const { folderTree, folderCounts, browserReady, browserReadyLoading, currentFolder, expandedFolders } =
        useValues(workflowFoldersLogic)
    const { listLoaded } = useValues(workflowsListV2Logic)
    const { openFolder, selectTreeFolder, setExpandedFolders } = useActions(workflowFoldersLogic)
    return (
        <LemonTree
            data={folderTree}
            expandedItemIds={expandedFolders}
            onSetExpandedItemIds={setExpandedFolders}
            isItemActive={(item) => (item.record?.path ?? '') === (currentFolder ?? '')}
            onItemClick={(item) => openFolder(item?.record?.path || null)}
            // LemonTree passes the state before a click but the state after Enter, so read it from the logic instead.
            onFolderClick={(item) =>
                selectTreeFolder(item?.record?.path || null, !!item && expandedFolders.includes(item.id))
            }
            renderItem={(item) => (
                <span className="flex items-center gap-1 min-w-0">
                    <span className="truncate">{item.name}</span>
                    <span className="text-secondary text-xs tabular-nums" translate="no">
                        {browserReady && !browserReadyLoading && listLoaded
                            ? `(${folderCounts[item.record?.path ?? ''] ?? 0})`
                            : '…'}
                    </span>
                </span>
            )}
            defaultNodeIcon={<IconFolder />}
            virtualized
        />
    )
}
