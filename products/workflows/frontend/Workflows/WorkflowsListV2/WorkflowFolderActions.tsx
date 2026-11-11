import { getContext, useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { joinPath, parentPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import { WORKFLOW_FILES_DRAG_SCOPE } from './workflowFolderDragScopes'
import { folderNameError, workflowFoldersLogic } from './workflowFoldersLogic'
import { WorkflowNewFolderButton } from './WorkflowNewFolderButton'

const isMoving = (id: string | undefined): boolean =>
    projectTreeDataLogic.values.pendingActions.some((action) => action.item.id === id)

// A folder move is queued in two steps, a count check and then the move. The second step is queued in the same
// tick that clears the first, so the check waits for that tick before calling the move settled.
function folderMoveSettled(id: string | undefined): Promise<void> {
    return new Promise((resolve) => {
        const settle = (): void => {
            if (!isMoving(id)) {
                unsubscribe()
                resolve()
            }
        }
        const unsubscribe = getContext().store.subscribe(() => queueMicrotask(settle))
        settle()
    })
}

export function WorkflowFolderActions({ path, count }: { path: string; count: number }): JSX.Element | null {
    const { savedItems, folderPaths, takenFolderPaths, folderActionPending } = useValues(workflowFoldersLogic)
    const { pendingActions } = useValues(projectTreeDataLogic)
    const { moveItem } = useActions(projectTreeDataLogic)
    const { moveFileToFolder } = useActions(workflowFoldersLogic)
    const entry = savedItems.find((item) => item.type === 'folder' && item.path === path)
    if (path === 'Unfiled') {
        return null
    }
    const newSubfolderButton = (
        <span className="opacity-0 group-hover/row:opacity-100 focus-within:opacity-100">
            <WorkflowNewFolderButton parent={path} iconOnly />
        </span>
    )
    if (!entry) {
        return <div className="flex justify-end items-center gap-1">{newSubfolderButton}</div>
    }
    const name = splitPath(path).at(-1) ?? path
    const movingReason = pendingActions.some((action) => action.item.id === entry.id)
        ? 'This folder is still moving. Try again when it finishes.'
        : undefined
    const empty = count === 0 && !folderPaths.some((folder) => folder.startsWith(`${path}/`))
    return (
        <div className="flex justify-end items-center gap-1">
            {newSubfolderButton}
            <LemonMenu
                items={[
                    { label: 'Move to…', disabledReason: movingReason, onClick: () => moveFileToFolder(entry) },
                    {
                        label: 'Rename…',
                        disabledReason:
                            movingReason ??
                            (takenFolderPaths ? undefined : 'Checking existing folder names. Try again in a moment.'),
                        onClick: () =>
                            LemonDialog.openForm({
                                title: `Rename ${name}`,
                                initialValues: { name },
                                content: (
                                    <LemonField name="name">
                                        <LemonInput autoFocus />
                                    </LemonField>
                                ),
                                errors: {
                                    name: (next: string | undefined = '') =>
                                        folderNameError(next, parentPath(path), takenFolderPaths, path) ?? undefined,
                                },
                                shouldAwaitSubmit: true,
                                onSubmit: async ({ name: next }) => {
                                    moveItem(
                                        entry,
                                        joinPath([...splitPath(parentPath(path)), next.trim()]),
                                        false,
                                        WORKFLOW_FILES_DRAG_SCOPE
                                    )
                                    await folderMoveSettled(entry.id)
                                },
                            }),
                    },
                    {
                        label: 'Delete',
                        status: 'danger',
                        disabledReason: !empty
                            ? 'Move what is inside this folder first'
                            : (movingReason ?? (folderActionPending ? 'A folder action is in progress' : undefined)),
                        onClick: () =>
                            LemonDialog.openForm({
                                title: `Delete ${name}?`,
                                initialValues: {},
                                content: (
                                    <span>
                                        Only an empty folder can be deleted. Files from other products also prevent
                                        deletion.
                                    </span>
                                ),
                                errors: {},
                                onSubmit: () => workflowFoldersLogic.asyncActions.deleteFolder(path),
                            }),
                    },
                ]}
            >
                <LemonButton
                    size="xsmall"
                    icon={<IconEllipsis />}
                    aria-label={`Actions for folder ${name}`}
                    loading={folderActionPending || !!movingReason}
                />
            </LemonMenu>
        </div>
    )
}
