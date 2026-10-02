import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill-primitives'

import { taskRunArtifactsLogic } from '../taskRunArtifactsLogic'

/** Asks before a save replaces a version that someone else wrote, or restores a file that was dismissed. */
export function ArtifactSaveConflictDialog({ taskId }: { taskId: string }): JSX.Element {
    const { editConflict, editSaving } = useValues(taskRunArtifactsLogic({ taskId }))
    const { resolveEditConflict } = useActions(taskRunArtifactsLogic({ taskId }))
    const dismissed = editConflict === 'dismissed'
    return (
        <AlertDialog
            open={editConflict !== null}
            onOpenChange={(open: boolean) => {
                if (!open && !editSaving) {
                    resolveEditConflict('keep_editing')
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>
                        {dismissed ? 'This file was dismissed' : 'A newer version is available'}
                    </AlertDialogTitle>
                    <AlertDialogDescription>
                        {dismissed
                            ? 'Every version of this file was dismissed while you were editing. Save your changes to restore it as the latest version?'
                            : 'A newer version of this file was saved while you were editing. Save your changes as the latest version anyway?'}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose
                        disabled={editSaving}
                        render={
                            <Button
                                variant="outline"
                                disabled={editSaving}
                                data-attr="task-artifact-conflict-keep-editing"
                            />
                        }
                    >
                        Keep editing
                    </AlertDialogClose>
                    <Button
                        variant="primary"
                        loading={editSaving}
                        onClick={() => resolveEditConflict('save_as_latest')}
                        data-attr="task-artifact-conflict-save"
                    >
                        {dismissed ? 'Save and restore' : 'Save as latest'}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
