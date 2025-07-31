import { IconGraph, IconLogomark, IconToggle, IconWarning, IconPieChart, IconMessage } from '@posthog/icons'
import {
    DetailsRenderProps,
    PreviewRenderProps,
    SessionTimelineEvent,
    SessionTimelineItem,
    SessionTimelineRenderer,
} from './base'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { JSONViewer } from 'lib/components/JSONViewer'
import { ErrorTrackingException } from 'lib/components/Errors/types'

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

export function EventPreview({ item }: PreviewRenderProps<SessionTimelineEvent>): JSX.Element {
    return (
        <div>
            <span className="font-medium">{sanitizeEventName(item.payload.event)}</span>
        </div>
    )
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

export const eventRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    predicate: (item: SessionTimelineItem) => item.type === 'event',
    icon: IconGraph,
    renderPreview: EventPreview,
    renderDetails: EventDetails,
    group: 'product-analytics',
}

export const pageviewRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    predicate: (item: SessionTimelineItem) =>
        eventRenderer.predicate(item) && (item.payload.event === '$screen' || item.payload.event === '$pageview'),
    icon: IconGraph,
    renderPreview: ({ item }): JSX.Element => {
        return (
            <div className="flex justify-between items-center">
                <span className="font-medium">{sanitizeEventName(item.payload.event)}</span>
                <span className="text-secondary text-xs">
                    {getUrlPathname(item.payload.properties['$current_url'])}
                </span>
            </div>
        )
    },
}

export const exceptionRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    predicate: (item: SessionTimelineItem) => eventRenderer.predicate(item) && item.payload.event === '$exception',
    icon: IconWarning,
    group: 'error-tracking',
    renderPreview: ({ item }): JSX.Element => {
        return (
            <div className="flex justify-between items-center w-full">
                <span className="font-medium">
                    {getExceptionType(item.payload.properties['$exception_list']) ||
                        sanitizeEventName(item.payload.event)}
                </span>
                <span className="text-secondary text-xs line-clamp-1 max-w-1/2 text-right">
                    {getExceptionMessage(item.payload.properties['$exception_list'])}
                </span>
            </div>
        )
    },
}

export const featureFlagRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    predicate: (item: SessionTimelineItem) =>
        eventRenderer.predicate(item) &&
        ['$feature_flag_called', '$feature_flag_response'].includes(item.payload.event),
    icon: IconToggle,
    group: 'feature-flags',
}

export const webAnalyticsRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    predicate: (item: SessionTimelineItem) =>
        eventRenderer.predicate(item) && ['$web_vitals'].includes(item.payload.event),
    icon: IconPieChart,
    group: 'web-analytics',
}

export const surveysRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    predicate: (item: SessionTimelineItem) =>
        eventRenderer.predicate(item) &&
        ['survey shown', 'survey dismissed', 'survey sent'].includes(item.payload.event),
    icon: IconMessage,
    group: 'surveys',
}

export const pageleaveRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    predicate: (item: SessionTimelineItem) => eventRenderer.predicate(item) && item.payload.event === '$pageleave',
    icon: IconGraph,
    group: 'product-analytics',
}

export const autocaptureRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    predicate: (item: SessionTimelineItem) => eventRenderer.predicate(item) && item.payload.event === '$autocapture',
    icon: IconGraph,
    group: 'product-analytics',
}

export const coreRenderer: SessionTimelineRenderer<SessionTimelineEvent> = {
    ...eventRenderer,
    predicate: (item: SessionTimelineItem) =>
        eventRenderer.predicate(item) && !!CORE_FILTER_DEFINITIONS_BY_GROUP.events[item.payload.event],
    group: 'internals',
    icon: IconLogomark,
}
