import {
    PreviewRenderProps,
    RendererGroup,
    SessionTimelineEvent,
    SessionTimelineItem,
    SessionTimelineRenderer,
} from './base'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'

import { ErrorTrackingException } from 'lib/components/Errors/types'
import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'
import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'

function sanitizeEventName(event: string): string {
    if (event.startsWith('$')) {
        return event
            .slice(1)
            .replace(/([A-Z])/g, ' $1')
            .replace(/([a-z])([A-Z])/g, '$1 $2')
            .replace(/_/g, ' ')
            .trim()
            .replace(/\b\w/g, (char) => char.toUpperCase())
    }
    return event
}

function getUrlPathname(url: string): string {
    try {
        const parsedUrl = new URL(url)
        return parsedUrl.pathname
    } catch {
        return url
    }
}

function getExceptionType(exceptionList: ErrorTrackingException[]): string | undefined {
    try {
        const firstException = exceptionList[0]
        if (firstException) {
            return firstException.type
        }
    } catch {
        return undefined
    }
}

function getExceptionMessage(exceptionList: ErrorTrackingException[]): string | undefined {
    try {
        const firstException = exceptionList[0]
        if (firstException) {
            return firstException.value
        }
    } catch {
        return undefined
    }
}

export function BasePreview({
    name,
    description,
}: {
    name: React.ReactNode
    description?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex justify-between items-center">
            <span className="font-medium">{name}</span>
            {description && (
                <span className="text-secondary text-xs line-clamp-1 max-w-2/3 text-right">{description}</span>
            )}
        </div>
    )
}

export function EventPreview({ item }: PreviewRenderProps<SessionTimelineEvent>): JSX.Element {
    return <BasePreview name={sanitizeEventName(item.payload.event)} />
}

function eventPredicate(item: SessionTimelineEvent, ...names: string[]): boolean {
    return item.type === 'event' && (names.length == 0 || names.includes(item.payload.event))
}

export const eventRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    predicate: (item: SessionTimelineEvent) => eventPredicate(item),
    runtimeIcon: ({ item }) => {
        const runtime = getRuntimeFromLib(item.payload.properties['$lib'])
        return <RuntimeIcon runtime={runtime} />
    },
    renderPreview: EventPreview,
    group: RendererGroup.PRODUCT_ANALYTICS,
}

export const pageRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    predicate: (item: SessionTimelineItem) => eventPredicate(item, '$screen', '$pageview', '$pageleave'),
    renderPreview: ({ item }): JSX.Element => {
        return (
            <BasePreview
                name={sanitizeEventName(item.payload.event)}
                description={
                    <Link
                        className="text-secondary hover:text-accent"
                        subtle
                        to={item.payload.properties['$current_url']}
                        target="_blank"
                    >
                        {getUrlPathname(item.payload.properties['$current_url'])}
                    </Link>
                }
            />
        )
    },
}

export const exceptionRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    group: RendererGroup.ERROR_TRACKING,
    predicate: (item: SessionTimelineItem) => eventPredicate(item, '$exception'),
    renderPreview: ({ item }): JSX.Element => {
        const name =
            getExceptionType(item.payload.properties['$exception_list']) || sanitizeEventName(item.payload.event)
        const description = getExceptionMessage(item.payload.properties['$exception_list'])
        const eventIssueId = item.payload.properties['$exception_issue_id']
        return (
            <BasePreview
                name={name}
                description={
                    <Link
                        className="text-secondary hover:text-accent"
                        subtle
                        to={urls.errorTrackingIssue(eventIssueId, {
                            fingerprint: item.payload.properties['$exception_fingerprint'],
                            timestamp: item.timestamp,
                        })}
                        onClick={() => {}}
                    >
                        {description}
                    </Link>
                }
            />
        )
    },
}

export const featureFlagRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    group: RendererGroup.FEATURE_FLAGS,
    predicate: (item: SessionTimelineItem) => eventPredicate(item, '$feature_flag_called', '$feature_flag_response'),
}

export const webAnalyticsRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    group: RendererGroup.WEB_ANALYTICS,
    predicate: (item: SessionTimelineItem) => eventPredicate(item, '$web_vitals'),
}

export const surveysRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    group: RendererGroup.SURVEYS,
    predicate: (item: SessionTimelineItem) => eventPredicate(item, 'survey shown', 'survey dismissed', 'survey sent'),
}

export const autocaptureRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    predicate: (item: SessionTimelineItem) => eventPredicate(item, '$autocapture'),
}

export const coreRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    group: RendererGroup.INTERNALS,
    predicate: (item: SessionTimelineItem) =>
        eventPredicate(item) && !!CORE_FILTER_DEFINITIONS_BY_GROUP.events[item.payload.event],
}
