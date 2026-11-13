import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { parentPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import { folderNameError, workflowFoldersLogic } from './workflowFoldersLogic'
import { WorkflowNewFolderButton } from './WorkflowNewFolderButton'

export function WorkflowFolderActions({ path, count }: { path: string; count: number }): JSX.Element | null {
    const {
        savedItems,
        folderPaths,
        takenFolderPaths,
        folderActionPending,
        folderChangeDisabledReason,
        folderNamesUnavailableReason,
    } = useValues(workflowFoldersLogic)
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
    const movingReason = folderChangeDisabledReason(path) ?? undefined
    const empty = count === 0 && !folderPaths.some((folder) => folder.startsWith(`${path}/`))
    return (
        <div className="flex justify-end items-center gap-1">
            {newSubfolderButton}
            <LemonMenu
                items={[
                    { label: 'Move to…', disabledReason: movingReason, onClick: () => moveFileToFolder(entry) },
                    {
                        label: 'Rename…',
                        disabledReason: movingReason ?? folderNamesUnavailableReason ?? undefined,
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
                                primaryButtonProps: { children: 'Rename' },
                                onSubmit: ({ name: next }) =>
                                    workflowFoldersLogic.asyncActions.renameFolder(path, next),
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
                                primaryButtonProps: { children: 'Delete', status: 'danger' },
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
