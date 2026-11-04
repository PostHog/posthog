import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { joinPath, parentPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import { workflowFoldersLogic } from './workflowFoldersLogic'
import { WorkflowNewFolderButton } from './WorkflowNewFolderButton'

export function WorkflowFolderActions({ path, count }: { path: string; count: number }): JSX.Element | null {
    const { savedItems, folderPaths, folderActionPending } = useValues(workflowFoldersLogic)
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
    const empty = count === 0 && !folderPaths.some((folder) => folder.startsWith(`${path}/`))
    return (
        <div className="flex justify-end items-center gap-1">
            {newSubfolderButton}
            <LemonMenu
                items={[
                    { label: 'Move to…', onClick: () => moveFileToFolder(entry) },
                    {
                        label: 'Rename…',
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
                                        !next.trim()
                                            ? 'Give the folder a name'
                                            : next.includes('/')
                                              ? 'Folder names cannot contain /'
                                              : next.trim() !== name &&
                                                  folderPaths.includes(
                                                      joinPath([...splitPath(parentPath(path)), next.trim()])
                                                  )
                                                ? 'A folder with this name already exists'
                                                : undefined,
                                },
                                onSubmit: ({ name: next }) =>
                                    moveItem(
                                        entry,
                                        joinPath([...splitPath(parentPath(path)), next.trim()]),
                                        false,
                                        'workflow-project-files'
                                    ),
                            }),
                    },
                    {
                        label: 'Delete',
                        status: 'danger',
                        disabledReason: !empty
                            ? 'Move what is inside this folder first'
                            : folderActionPending
                              ? 'A folder action is in progress'
                              : undefined,
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
                    loading={folderActionPending}
                />
            </LemonMenu>
        </div>
    )
}
