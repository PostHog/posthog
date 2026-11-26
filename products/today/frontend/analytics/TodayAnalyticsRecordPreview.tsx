import { useMemo } from 'react'

import { AnalyticsSpaceGlyph } from 'scenes/analytics/AnalyticsSpaceGlyph'
import { AnalyticsType } from 'scenes/analytics/analyticsUtils'

import { TodayExplainerPreview } from '~/layout/today/todayPreviewCards'
import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'
import { todayRecordType } from '~/layout/today/todayRecordTypes'

import { AnalyticsItemIcon } from './AnalyticsItemIcon'

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
            description: todayRecordType(type).description,
        }),
        [name, type]
    )
    return <TodayPreviewTrigger payload={preview}>{children}</TodayPreviewTrigger>
}
