import { useActions, useValues } from 'kea'

import { IconEllipsis, IconSparkles } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import type { HealthIssue } from 'scenes/health/types'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import { stoppedEventsLogic } from './stoppedEventsLogic'
import { stoppedEventPayload } from './stoppedEventText'

export function StoppedEventActions({ issue }: { issue: HealthIssue }): JSX.Element {
    const { postHogAIOpen } = useValues(stoppedEventsLogic)
    const { investigateWithPostHogAI, reportActionClicked, dismissIssue, snoozeIssue } = useActions(stoppedEventsLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const payload = stoppedEventPayload(issue)

    return (
        <div className="flex items-center justify-end gap-2">
            <Button
                variant="outline"
                size="sm"
                render={<LinkPrimitive to={urls.eventDefinition(payload.event_definition_id)} />}
                onClick={() => reportActionClicked('view_event', issue)}
                data-attr="stopped-event-view-event"
            >
                View event
            </Button>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="outline"
                            size="icon"
                            aria-label="More options"
                            tooltip="More options"
                            data-attr="stopped-event-options"
                        />
                    }
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-56">
                    {dataProcessingAccepted && (
                        <DropdownMenuItem
                            disabled={postHogAIOpen}
                            onClick={() => investigateWithPostHogAI(issue)}
                            data-attr="stopped-event-investigate-with-ai"
                        >
                            <IconSparkles />
                            Investigate with PostHog AI
                        </DropdownMenuItem>
                    )}
                    <DropdownMenuItem onClick={() => snoozeIssue(issue)} data-attr="stopped-event-snooze">
                        Snooze for 7 days
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => dismissIssue(issue)} data-attr="stopped-event-dismiss">
                        I stopped sending this on purpose
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
