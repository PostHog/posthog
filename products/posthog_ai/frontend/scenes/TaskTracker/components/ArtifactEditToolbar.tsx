import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Badge,
    Button,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill-primitives'

import { taskRunArtifactsLogic } from '../taskRunArtifactsLogic'

/** The toolbar while a file is open in the editor. `expandAction` is the full page toggle of the preview toolbar. */
export function ArtifactEditToolbar({
    taskId,
    expandAction,
}: {
    taskId: string
    expandAction: JSX.Element
}): JSX.Element | null {
    const { editSession, editDirty, editSaving } = useValues(taskRunArtifactsLogic({ taskId }))
    const { saveEdit, cancelEditing } = useActions(taskRunArtifactsLogic({ taskId }))
    if (!editSession) {
        return null
    }
    const saveButton = (
        <Button
            variant="primary"
            loading={editSaving}
            disabled={!editDirty}
            onClick={() => saveEdit()}
            data-attr="task-artifact-edit-save"
        >
            Save
        </Button>
    )
    return (
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-background px-3">
            <IconPencil className="size-4 shrink-0 text-muted-foreground" />
            <Text size="sm" weight="medium" render={<span />} className="min-w-0 truncate">
                {editSession.name}
            </Text>
            <Badge variant="info" className="shrink-0">
                Editing
            </Badge>
            <div className="ml-auto flex shrink-0 items-center gap-1">
                {editDirty ? (
                    <AlertDialog>
                        <AlertDialogTrigger
                            disabled={editSaving}
                            render={
                                <Button variant="outline" disabled={editSaving} data-attr="task-artifact-edit-cancel" />
                            }
                        >
                            Cancel
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                            <AlertDialogHeader>
                                <AlertDialogTitle>Discard your changes?</AlertDialogTitle>
                                <AlertDialogDescription>
                                    {`Your changes to ${editSession.name} aren't saved. If you discard them, you can't get them back.`}
                                </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                                <AlertDialogClose render={<Button variant="outline" />}>Keep editing</AlertDialogClose>
                                <AlertDialogClose
                                    render={
                                        <Button
                                            variant="destructive-outline"
                                            onClick={() => cancelEditing()}
                                            data-attr="task-artifact-edit-discard"
                                        />
                                    }
                                >
                                    Discard changes
                                </AlertDialogClose>
                            </AlertDialogFooter>
                        </AlertDialogContent>
                    </AlertDialog>
                ) : (
                    <Button
                        variant="outline"
                        disabled={editSaving}
                        onClick={() => cancelEditing()}
                        data-attr="task-artifact-edit-cancel"
                    >
                        Cancel
                    </Button>
                )}
                {editDirty ? (
                    saveButton
                ) : (
                    <Tooltip>
                        <TooltipTrigger render={saveButton} />
                        <TooltipContent>There are no changes to save</TooltipContent>
                    </Tooltip>
                )}
                {expandAction}
            </div>
        </div>
    )
}
