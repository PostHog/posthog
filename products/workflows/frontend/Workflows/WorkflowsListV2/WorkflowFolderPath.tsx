import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { joinPath, parentPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import { workflowFoldersLogic } from './workflowFoldersLogic'
import { displayedFolder } from './workflowListFacets'

export function WorkflowFolderPath({ path }: { path: string }): JSX.Element | null {
    const { currentFolder, hasActiveQuery } = useValues(workflowFoldersLogic)
    const { openFolder } = useActions(workflowFoldersLogic)
    if (!hasActiveQuery) {
        return null
    }
    // An unfiled file sits under a product subfolder that the view shows as plain Unfiled.
    const segments = splitPath(displayedFolder(parentPath(path)))
    const offset = splitPath(currentFolder ?? '').length
    return (
        <span className="flex min-w-0 text-secondary overflow-hidden">
            {segments.slice(offset).map((segment, index) => (
                <span className="flex min-w-0 items-center" key={index}>
                    <LemonButton
                        size="xsmall"
                        onClick={() => openFolder(joinPath(segments.slice(0, offset + index + 1)))}
                        className="truncate"
                    >
                        {segment}
                    </LemonButton>
                    <span className="shrink-0">/</span>
                </span>
            ))}
        </span>
    )
}
