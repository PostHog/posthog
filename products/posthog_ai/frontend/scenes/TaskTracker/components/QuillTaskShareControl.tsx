import { useActions, useValues } from 'kea'
import { RefObject, useRef } from 'react'

import { IconChevronDown, IconGlobe, IconLock, IconPeople, IconRefresh, IconShare } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { IconLink } from 'lib/lemon-ui/icons'
import { teamLogic } from 'scenes/teamLogic'

import { TaskVisibility, taskShareLogic } from '../taskShareLogic'

const LABELS: Record<TaskVisibility, string> = { private: 'Private', public: 'Public', shared: 'Shared' }
const ICONS: Record<TaskVisibility, JSX.Element> = {
    private: <IconLock />,
    public: <IconGlobe />,
    shared: <IconPeople />,
}

function ShareTaskDialog({
    taskId,
    open,
    controlRef,
}: {
    taskId: string
    open: boolean
    controlRef: RefObject<HTMLDivElement | null>
}): JSX.Element {
    const logic = taskShareLogic({ taskId })
    const { visibilityChanging } = useValues(logic)
    const { closeShareDialog, setVisibility } = useActions(logic)
    const { currentTeam } = useValues(teamLogic)
    const project = currentTeam?.name ? `Everyone in ${currentTeam.name}` : 'Everyone in this project'

    return (
        <AlertDialog
            open={open}
            onOpenChange={(nextOpen: boolean) => {
                if (!nextOpen && !visibilityChanging) {
                    closeShareDialog()
                }
            }}
        >
            <AlertDialogContent
                // A share swaps the Share button for the Public menu, so focus the button that is there now.
                finalFocus={() => controlRef.current?.querySelector<HTMLElement>('button') ?? true}
            >
                <AlertDialogHeader>
                    <AlertDialogTitle>Make this task public?</AlertDialogTitle>
                    <AlertDialogDescription>
                        {`${project} can see this task and its chat. We copy the link for you.`}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => closeShareDialog()}
                        disabled={visibilityChanging}
                        data-attr="task-share-cancel"
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={visibilityChanging}
                        onClick={() => setVisibility('public')}
                        data-attr="task-share-confirm"
                    >
                        <IconGlobe />
                        Make public
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}

function ShareControlButton({ taskId }: { taskId: string }): JSX.Element | null {
    const logic = taskShareLogic({ taskId })
    const { visibility, isCreator, visibilityChanging, shareStateLoadFailed, shareStateLoading } = useValues(logic)
    const { openShareDialog, setVisibility, copyLink, loadShareState } = useActions(logic)

    if (shareStateLoadFailed) {
        return (
            <Button
                variant="outline"
                loading={shareStateLoading}
                onClick={() => loadShareState()}
                title="Could not load who can see this task. Click to try again."
                data-attr="task-share-retry"
            >
                <IconRefresh />
                Share
            </Button>
        )
    }
    if (!visibility || (visibility === 'private' && !isCreator)) {
        return null
    }
    if (visibility === 'private') {
        return (
            <Button
                variant="outline"
                loading={visibilityChanging}
                onClick={() => openShareDialog()}
                data-attr="task-share"
            >
                <IconShare />
                Share
            </Button>
        )
    }
    if (!isCreator) {
        return (
            <Badge aria-label={LABELS[visibility]}>
                {ICONS[visibility]}
                {LABELS[visibility]}
            </Badge>
        )
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        loading={visibilityChanging}
                        aria-label={`${LABELS[visibility]}. Change who can see this task`}
                        data-attr="task-visibility"
                    />
                }
            >
                {ICONS[visibility]}
                {LABELS[visibility]}
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-48">
                <DropdownMenuItem onClick={() => copyLink()} data-attr="task-copy-link">
                    <IconLink />
                    Copy link
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => setVisibility('private')} data-attr="task-make-private">
                    <IconLock />
                    Make private
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

export function QuillTaskShareControl({ taskId }: { taskId: string }): JSX.Element {
    const { isCreator, shareDialogOpen } = useValues(taskShareLogic({ taskId }))
    const controlRef = useRef<HTMLDivElement>(null)

    return (
        <div data-quill className="contents" ref={controlRef}>
            <ShareControlButton taskId={taskId} />
            {isCreator && <ShareTaskDialog taskId={taskId} open={shareDialogOpen} controlRef={controlRef} />}
        </div>
    )
}
