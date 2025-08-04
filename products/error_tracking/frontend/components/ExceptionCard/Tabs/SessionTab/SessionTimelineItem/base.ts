import { IconComponent } from '@posthog/icons/dist/src/types/icon-types'

export interface PreviewRenderProps<T> {
    item: T
    selected: boolean
}

export interface DetailsRenderProps<T> extends PreviewRenderProps<T> {}

export type SessionTimelineEvent = {
    id: string
    type: 'event'
    timestamp: string
    payload: {
        event: string
        properties: Record<string, any>
    }
}

export type SessionTimelineItem = SessionTimelineEvent

export enum RendererGroup {
    ERROR_TRACKING = 'error-tracking',
    PRODUCT_ANALYTICS = 'product-analytics',
    WEB_ANALYTICS = 'web-analytics',
    SURVEYS = 'surveys',
    FEATURE_FLAGS = 'feature-flags',
    INTERNALS = 'internals',
}

export type SessionTimelineRenderer<T> = {
    predicate: (item: SessionTimelineItem) => boolean
    runtimeIcon: IconComponent<PreviewRenderProps<T>>
    group: RendererGroup
    renderPreview: React.FC<PreviewRenderProps<T>>
    renderDetails: React.FC<DetailsRenderProps<T>>
}
