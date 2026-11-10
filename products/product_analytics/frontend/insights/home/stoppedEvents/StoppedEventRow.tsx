import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconEllipsis, IconSparkles } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, Text } from '@posthog/quill'

import { Link, LinkPrimitive } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import type { HealthIssue } from 'scenes/health/types'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import { SavedInsightsTabs } from '~/types'

import { stoppedEventsLogic } from './stoppedEventsLogic'
import {
    stoppedEventAnnotationText,
    stoppedEventLastCapture,
    stoppedEventLastSeen,
    stoppedEventPayload,
} from './stoppedEventText'

export function StoppedEventRow({ issue }: { issue: HealthIssue }): JSX.Element {
    const { postHogAIOpen } = useValues(stoppedEventsLogic)
    const { investigateWithPostHogAI, reportActionClicked, dismissIssue, snoozeIssue } = useActions(stoppedEventsLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const payload = stoppedEventPayload(issue)
    const annotation = stoppedEventAnnotationText(payload)
    const lastCapture = stoppedEventLastCapture(payload)

    return (
        <li
            className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-primary px-4 py-3 last:border-b-0"
            data-attr="stopped-event"
        >
            <div className="flex min-w-0 flex-col">
                <Text weight="medium" render={<span />} className="break-all">
                    {payload.event}
                </Text>
                <Text size="xs" variant="muted" render={<span />}>
                    {stoppedEventLastSeen(payload)} · used in{' '}
                    <Link
                        to={combineUrl(urls.savedInsights(SavedInsightsTabs.All), { events: [payload.event] }).url}
                        onClick={() => reportActionClicked('review_insights', issue)}
                        data-attr="stopped-event-review-insights"
                    >
                        {pluralize(payload.insight_count, 'insight')}
                    </Link>
                </Text>
                {lastCapture && (
                    <Text size="xs" variant="muted" render={<span />} className="break-all">
                        {lastCapture}
                    </Text>
                )}
                {annotation && (
                    <Text size="xs" variant="muted" render={<span />}>
                        {annotation}
                    </Text>
                )}
            </div>
            <div className="flex items-center gap-2">
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
        </li>
    )
}
