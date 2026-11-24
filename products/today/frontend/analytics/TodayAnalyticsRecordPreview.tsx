import { useMemo } from 'react'

import { AnalyticsSpaceGlyph } from 'scenes/analytics/AnalyticsSpaceGlyph'
import { AnalyticsType } from 'scenes/analytics/analyticsUtils'

import { TodayExplainerPreview } from '~/layout/today/todayPreviewCards'
import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'

import { AnalyticsItemIcon } from './AnalyticsItemIcon'

const DESCRIPTIONS: Record<AnalyticsType | 'collection', string> = {
    canvas: 'A canvas. Open it to see the page built from your data.',
    dashboard: 'A dashboard. Open it to see its insights and widgets.',
    insight: 'An insight. Open it to see its chart and the query behind it.',
    notebook: 'A notebook. Open it to read its analysis.',
    collection: 'A collection. Open it to see the analytics kept in it.',
}

export function TodayAnalyticsRecordPreview({
    name,
    type,
    children,
}: {
    name: string
    type: AnalyticsType | 'collection'
    children: JSX.Element
}): JSX.Element {
    // The shared card stores the payload, so it must keep its identity between renders.
    const preview = useMemo<TodayExplainerPreview>(
        () => ({
            kind: 'explainer',
            label: name,
            icon: type === 'collection' ? <AnalyticsSpaceGlyph name={name} /> : <AnalyticsItemIcon type={type} />,
            description: DESCRIPTIONS[type],
        }),
        [name, type]
    )
    return <TodayPreviewTrigger payload={preview}>{children}</TodayPreviewTrigger>
}
