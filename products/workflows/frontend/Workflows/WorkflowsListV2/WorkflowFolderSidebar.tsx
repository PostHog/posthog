import { useActions, useValues } from 'kea'

import { IconSidebarClose } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { workflowFoldersLogic } from './workflowFoldersLogic'
import { WorkflowFolderTree } from './WorkflowFolderTree'

export function WorkflowFolderSidebar(): JSX.Element {
    const { folderSidebarCollapsed } = useValues(workflowFoldersLogic)
    const { setFolderSidebarCollapsed } = useActions(workflowFoldersLogic)

    if (folderSidebarCollapsed) {
        return (
            <nav
                aria-label="Project files"
                className="hidden @min-[48rem]/main-content:flex flex-col items-center border rounded p-1 shrink-0 self-stretch bg-surface-primary"
            >
                <LemonButton
                    icon={<IconSidebarClose />}
                    size="xsmall"
                    tooltip="Show folders"
                    aria-label="Show folders"
                    onClick={() => setFolderSidebarCollapsed(false)}
                    data-attr="workflows-folder-sidebar-expand"
                />
            </nav>
        )
    }

    return (
        <nav
            aria-label="Project files"
            className="hidden @min-[48rem]/main-content:flex flex-col border rounded p-1 @min-[48rem]/main-content:w-52 @min-[64rem]/main-content:w-60 shrink-0 self-stretch bg-surface-primary"
        >
            <div className="flex items-center justify-between gap-1 pl-2">
                <span className="text-xs font-semibold text-secondary">Folders</span>
                <LemonButton
                    icon={<IconSidebarClose className="rotate-180" />}
                    size="xsmall"
                    tooltip="Hide folders"
                    aria-label="Hide folders"
                    onClick={() => setFolderSidebarCollapsed(true)}
                    data-attr="workflows-folder-sidebar-collapse"
                />
            </div>
            <WorkflowFolderTree />
        </nav>
    )
}
