import { useActions, useValues } from 'kea'

import { IconChevronDown, IconGlobe, IconLock, IconPeople, IconShare } from '@posthog/icons'
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

function ShareTaskDialog({ taskId }: { taskId: string }): JSX.Element {
    const logic = taskShareLogic({ taskId })
    const { visibilityChanging } = useValues(logic)
    const { closeShareDialog, setVisibility } = useActions(logic)
    const { currentTeam } = useValues(teamLogic)
    const project = currentTeam?.name ? `Everyone in ${currentTeam.name}` : 'Everyone in this project'

    return (
        <AlertDialog
            open
            onOpenChange={(open: boolean) => {
                if (!open && !visibilityChanging) {
                    closeShareDialog()
                }
            }}
        >
            <AlertDialogContent>
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

export function QuillTaskShareControl({ taskId }: { taskId: string }): JSX.Element | null {
    const logic = taskShareLogic({ taskId })
    const { visibility, isCreator, visibilityChanging, shareDialogOpen } = useValues(logic)
    const { openShareDialog, setVisibility, copyLink } = useActions(logic)

    if (!visibility) {
        return null
    }

    if (visibility === 'private') {
        if (!isCreator) {
            return null
        }
        return (
            <div data-quill className="contents">
                <Button
                    variant="outline"
                    loading={visibilityChanging}
                    onClick={() => openShareDialog()}
                    data-attr="task-share"
                >
                    <IconShare />
                    Share
                </Button>
                {shareDialogOpen && <ShareTaskDialog taskId={taskId} />}
            </div>
        )
    }

    if (!isCreator) {
        return (
            <div data-quill className="contents">
                <Badge aria-label={LABELS[visibility]}>
                    {ICONS[visibility]}
                    {LABELS[visibility]}
                </Badge>
            </div>
        )
    }

    return (
        <div data-quill className="contents">
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
        </div>
    )
}
