import { useValues } from 'kea'

import { LemonBanner, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { Query } from '~/queries/Query/Query'
import { AnyResponseType, MetricsHistogramQuery, MetricsQuery } from '~/queries/schema/schema-general'

import type { MetricsSampledTemplatePanelApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsDashboardReviewSceneLogic } from './metricsDashboardReviewSceneLogic'

// Static class names, so that Tailwind generates them. The index is the panel width in grid columns.
const COLUMN_SPAN = [
    '',
    '@3xl:col-span-1',
    '@3xl:col-span-2',
    '@3xl:col-span-3',
    '@3xl:col-span-4',
    '@3xl:col-span-5',
    '@3xl:col-span-6',
    '@3xl:col-span-7',
    '@3xl:col-span-8',
    '@3xl:col-span-9',
    '@3xl:col-span-10',
    '@3xl:col-span-11',
    '@3xl:col-span-12',
]

function SamplePanel({ panel }: { panel: MetricsSampledTemplatePanelApi }): JSX.Element {
    return (
        <div
            className={cn(
                'flex flex-col gap-1 h-64 min-w-0 border rounded bg-surface-primary p-2',
                COLUMN_SPAN[Math.min(Math.max(panel.layout.w, 1), 12)]
            )}
        >
            <div className="flex items-center gap-2 min-w-0">
                <span className="font-semibold truncate">{panel.title}</span>
                <LemonTag type="muted" size="small">
                    Sample values
                </LemonTag>
            </div>
            <div className="flex flex-1 min-h-0">
                <Query
                    query={panel.query as unknown as MetricsQuery | MetricsHistogramQuery}
                    cachedResults={panel.response as AnyResponseType}
                    readOnly
                    embedded
                />
            </div>
        </div>
    )
}

export function SamplePanels(): JSX.Element | null {
    const { samplePanels, previewDashboardId } = useValues(metricsDashboardReviewSceneLogic)

    if (!samplePanels.length) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonBanner type="info">
                {previewDashboardId
                    ? 'This project does not send the metrics of the charts below, so they show made-up sample values.'
                    : 'This project sends none of the metrics of this dashboard, so the charts show made-up sample values.'}
            </LemonBanner>
            <div className="@container">
                <div className="grid grid-cols-1 @3xl:grid-cols-12 gap-2">
                    {samplePanels.map((panel) => (
                        <SamplePanel key={panel.key} panel={panel} />
                    ))}
                </div>
            </div>
        </div>
    )
}
