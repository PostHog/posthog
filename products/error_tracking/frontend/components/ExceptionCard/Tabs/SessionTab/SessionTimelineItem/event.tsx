import {
    DetailsRenderProps,
    PreviewRenderProps,
    RendererGroup,
    SessionTimelineEvent,
    SessionTimelineItem,
    SessionTimelineRenderer,
} from './base'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { JSONViewer } from 'lib/components/JSONViewer'
import { ErrorTrackingException } from 'lib/components/Errors/types'
import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'
import { getRuntimeFromLib } from 'lib/components/Errors/utils'

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

export function BasePreview({ name, description }: { name: string; description?: string }): JSX.Element {
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

export function EventDetails({ item }: DetailsRenderProps<SessionTimelineEvent>): JSX.Element {
    return (
        <div className="p-2">
            <JSONViewer
                src={item.payload.properties}
                name="event"
                collapsed={1}
                collapseStringsAfterLength={80}
                sortKeys
            />
        </div>
    )
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
    renderDetails: EventDetails,
    group: RendererGroup.PRODUCT_ANALYTICS,
}

export const pageRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    predicate: (item: SessionTimelineItem) => eventPredicate(item, '$screen', '$pageview', '$pageleave'),
    renderPreview: ({ item }): JSX.Element => {
        return (
            <BasePreview
                name={sanitizeEventName(item.payload.event)}
                description={getUrlPathname(item.payload.properties['$current_url'])}
            />
        )
    },
}

export const exceptionRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    group: RendererGroup.ERROR_TRACKING,
    predicate: (item: SessionTimelineItem) => eventPredicate(item, '$exception'),
    renderPreview: ({ item }): JSX.Element => {
        return (
            <BasePreview
                name={
                    getExceptionType(item.payload.properties['$exception_list']) ||
                    sanitizeEventName(item.payload.event)
                }
                description={getExceptionMessage(item.payload.properties['$exception_list'])}
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
