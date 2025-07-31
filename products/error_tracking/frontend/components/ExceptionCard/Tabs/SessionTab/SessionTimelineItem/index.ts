import { SessionTimelineItem, SessionTimelineRenderer } from './base'
import {
    autocaptureRenderer,
    coreRenderer,
    eventRenderer,
    exceptionRenderer,
    featureFlagRenderer,
    pageleaveRenderer,
    pageviewRenderer,
} from './event'

export const timelineRenderers: SessionTimelineRenderer<any>[] = [
    pageviewRenderer,
    autocaptureRenderer,
    pageleaveRenderer,
    featureFlagRenderer,
    exceptionRenderer,
    coreRenderer,
    eventRenderer,
]

export function getTimelineRenderer<T>(item: SessionTimelineItem): SessionTimelineRenderer<T> | undefined {
    return timelineRenderers.find((renderer) => renderer.predicate(item))
}
