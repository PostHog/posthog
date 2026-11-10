import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconInfo, IconWarning } from '@posthog/icons'
import { LemonCard, LemonTable } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils/strings'
import type { HealthIssue } from 'scenes/health/types'
import { urls } from 'scenes/urls'

import { SavedInsightsTabs } from '~/types'

import { StoppedEventActions } from './StoppedEventActions'
import { stoppedEventsLogic } from './stoppedEventsLogic'
import {
    stoppedEventAnnotationText,
    stoppedEventDailyVolume,
    stoppedEventLastCapture,
    stoppedEventPayload,
    stoppedEventStoppedAgo,
} from './stoppedEventText'

/** Events that the product's insights read, which stopped arriving. Renders nothing until there is one to show. */
export function StoppedEventsNotice(): JSX.Element | null {
    const { visibleIssues } = useValues(stoppedEventsLogic)
    const { reportActionClicked } = useActions(stoppedEventsLogic)

    // The notice is optional, so it stays out of the layout while loading and when nothing stopped.
    if (!visibleIssues?.length) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="mb-4 overflow-hidden p-0" data-attr="stopped-events-notice">
            <div className="flex items-center gap-2 border-b border-primary px-4 py-2.5">
                <IconWarning className="size-4 text-warning" />
                <h2 className="m-0 text-sm font-semibold">
                    {visibleIssues.length === 1
                        ? 'An event your insights use stopped arriving'
                        : `${visibleIssues.length} events your insights use stopped arriving`}
                </h2>
            </div>
            <LemonTable<HealthIssue>
                embedded
                size="small"
                rowKey="id"
                dataSource={visibleIssues}
                columns={[
                    {
                        title: 'Event',
                        key: 'event',
                        render: (_, issue) => {
                            const payload = stoppedEventPayload(issue)
                            const lastCapture = stoppedEventLastCapture(payload)
                            return (
                                <div className="flex min-w-48 flex-col py-1" data-attr="stopped-event">
                                    <span className="font-semibold break-words">{payload.event}</span>
                                    {lastCapture && (
                                        <span className="text-xs text-secondary break-words">{lastCapture}</span>
                                    )}
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Events per day',
                        key: 'volume',
                        render: (_, issue) => {
                            const before = stoppedEventDailyVolume(stoppedEventPayload(issue))
                            return (
                                <span className="flex items-center gap-1.5 whitespace-nowrap font-semibold">
                                    {before && (
                                        <>
                                            <span className="text-success">{before}</span>
                                            <span className="text-secondary" aria-label="down to">
                                                →
                                            </span>
                                        </>
                                    )}
                                    <span className="text-danger">0</span>
                                </span>
                            )
                        },
                    },
                    {
                        title: 'Stopped',
                        key: 'stopped',
                        render: (_, issue) => {
                            const payload = stoppedEventPayload(issue)
                            const annotation = stoppedEventAnnotationText(payload)
                            return (
                                <span className="flex items-center gap-1 whitespace-nowrap">
                                    {stoppedEventStoppedAgo(payload)}
                                    {annotation && (
                                        <Tooltip title={annotation}>
                                            <IconInfo
                                                className="size-4 text-secondary"
                                                aria-label={annotation}
                                                data-attr="stopped-event-annotation"
                                            />
                                        </Tooltip>
                                    )}
                                </span>
                            )
                        },
                    },
                    {
                        title: 'Used in',
                        key: 'insights',
                        render: (_, issue) => {
                            const payload = stoppedEventPayload(issue)
                            return (
                                <Link
                                    to={
                                        combineUrl(urls.savedInsights(SavedInsightsTabs.All), {
                                            events: [payload.event],
                                        }).url
                                    }
                                    onClick={() => reportActionClicked('review_insights', issue)}
                                    data-attr="stopped-event-review-insights"
                                >
                                    <span className="whitespace-nowrap">
                                        {pluralize(payload.insight_count, 'insight')}
                                    </span>
                                </Link>
                            )
                        },
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, issue) => <StoppedEventActions issue={issue} />,
                    },
                ]}
            />
        </LemonCard>
    )
}
