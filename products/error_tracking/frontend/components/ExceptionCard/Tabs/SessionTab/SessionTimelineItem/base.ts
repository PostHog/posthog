import { IconComponent, IconProps } from '@posthog/icons/dist/src/types/icon-types'

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

export type RendererGroup =
    | 'error-tracking'
    | 'product-analytics'
    | 'web-analytics'
    | 'surveys'
    | 'feature-flags'
    | 'internals'

export type SessionTimelineRenderer<T> = {
    predicate: (item: SessionTimelineItem) => boolean
    icon: IconComponent<IconProps>
    group: RendererGroup
    renderPreview: React.FC<PreviewRenderProps<T>>
    renderDetails: React.FC<DetailsRenderProps<T>>
}
