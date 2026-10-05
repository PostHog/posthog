import { type ReactElement, useEffect } from 'react'

import { captureInsightDisplayChanged, captureInsightViewed } from '../analytics/posthog'
import { Component, type ComponentProps } from './Component'
import { inferVisualizationType } from './infer-visualization'
import { insightQueryProperties } from './utils'

/** `Component` with analytics. Kept apart so stories render `Component` without `posthog-js-lite`. */
export function TrackedComponent({ data }: Pick<ComponentProps, 'data'>): ReactElement {
    // `insight-query` also returns the saved insight, whose query keeps the wrapper node that `query` drops.
    const payload = data as { query?: unknown; insight?: { query?: unknown } } | null
    const isSupported = inferVisualizationType(data) !== null
    const { queryKind, querySourceKind, display, funnelVizType } = insightQueryProperties(
        payload?.insight?.query ?? payload?.query
    )

    useEffect(() => {
        captureInsightViewed({ queryKind, querySourceKind, display, funnelVizType, isSupported })
    }, [data, isSupported, queryKind, querySourceKind, display, funnelVizType])

    return <Component data={data} onDisplayChange={captureInsightDisplayChanged} />
}
