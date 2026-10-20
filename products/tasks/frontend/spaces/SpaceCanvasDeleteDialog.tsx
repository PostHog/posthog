import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

import { spaceSceneLogic } from './spaceSceneLogic'

export function SpaceCanvasDeleteDialog({ spaceId }: { spaceId: string }): JSX.Element {
    const { canvasDeleteTarget, canvasDeleting } = useValues(spaceSceneLogic({ id: spaceId }))
    const { setCanvasDeleteTarget, confirmCanvasDelete } = useActions(spaceSceneLogic({ id: spaceId }))

    return (
        <AlertDialog
            open={canvasDeleteTarget !== null}
            onOpenChange={(open: boolean) => {
                if (!open && !canvasDeleting) {
                    setCanvasDeleteTarget(null)
                }
            }}
        >
            <AlertDialogContent className="max-w-md">
                <AlertDialogHeader>
                    <AlertDialogTitle>Delete canvas</AlertDialogTitle>
                    <AlertDialogDescription>
                        Delete <span className="font-medium">{canvasDeleteTarget?.name || 'Untitled canvas'}</span>? Its
                        code and version history go for everyone in the space. You can’t undo this.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => setCanvasDeleteTarget(null)}
                        disabled={canvasDeleting}
                        data-attr="today-space-canvases-delete-cancel"
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        loading={canvasDeleting}
                        disabled={canvasDeleting}
                        onClick={() => confirmCanvasDelete()}
                        data-attr="today-space-canvases-delete-confirm"
                    >
                        Delete
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
