import { IconCopy, IconEllipsis, IconListCheck, IconRefresh, IconStopFilled } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill-primitives'

import type { WizardRunApi } from '../generated/api.schemas'
import { wizardRunCanCancel } from '../wizardRunDisplay'

export function WizardRunActionsMenu({
    run,
    currentUserId,
    refreshing,
    cancelling,
    onView,
    onRefresh,
    onCopyRunId,
    onCancel,
}: {
    run: WizardRunApi
    currentUserId: number | null
    refreshing: boolean
    cancelling: boolean
    onView: (run: WizardRunApi) => void
    onRefresh: (run: WizardRunApi) => void
    onCopyRunId: (runId: string) => void
    onCancel: (run: WizardRunApi) => void
}): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        size="icon-sm"
                        aria-label={`More options for ${run.program.name}`}
                        onClick={(event) => event.stopPropagation()}
                    >
                        <IconEllipsis />
                    </Button>
                }
            />
            <DropdownMenuContent align="end" className="min-w-56">
                <DropdownMenuItem onClick={() => onView(run)}>
                    <IconListCheck />
                    View run details
                </DropdownMenuItem>
                <DropdownMenuItem disabled={refreshing} onClick={() => onRefresh(run)}>
                    <IconRefresh />
                    {refreshing ? 'Refreshing…' : 'Refresh status'}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onCopyRunId(run.id)}>
                    <IconCopy />
                    Copy run ID
                </DropdownMenuItem>
                {wizardRunCanCancel(run, currentUserId) && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem variant="destructive" disabled={cancelling} onClick={() => onCancel(run)}>
                            <IconStopFilled />
                            {cancelling ? 'Canceling…' : 'Cancel run'}
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
