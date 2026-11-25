import { useValues } from 'kea'

import { Badge, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

export function IssueStillSeenCue(): JSX.Element | null {
    const { stillSeenAfterResolve } = useValues(errorTrackingIssueSceneLogic)

    if (!stillSeenAfterResolve) {
        return null
    }

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    // Focusable, so a keyboard user can open the tooltip too.
                    <Badge variant="info" tabIndex={0} data-attr="error-tracking-issue-still-seen">
                        Still seen in older releases
                    </Badge>
                }
            />
            <TooltipContent>
                Exceptions keep arriving after the resolve. They come from releases this issue was already seen in, or
                older ones, so they don't reopen it.
            </TooltipContent>
        </Tooltip>
    )
}
