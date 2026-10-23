import { useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { MetricsQuery } from '~/queries/schema/schema-general'

import { MetricsQueryEditorSection } from '../components/MetricsQueryEditorSection'
import { MetricsWidgetQueryPreview } from './MetricsWidgetQueryPreview'

let uniquePreview = 0

/** Edits a metric widget's query with the metrics builder, PromQL or SQL, above a live preview of the tile. */
export function MetricsWidgetQueryEditor({
    query,
    setQuery,
    onUnrunTextChange,
}: {
    query: MetricsQuery
    setQuery: (query: MetricsQuery) => void
    /** Gets whether the PromQL or SQL editor holds text that has not run yet. */
    onUnrunTextChange?: (unrun: boolean) => void
}): JSX.Element {
    const [dataKey] = useState(() => `MetricsWidgetQueryPreview.${uniquePreview++}`)
    // The same audience as the metrics insight builder can edit a metric widget's query.
    const builderEnabled = useFeatureFlag('METRICS_INSIGHT_BUILDER')

    return (
        <div className="flex flex-col gap-3 min-w-0">
            {builderEnabled ? (
                <MetricsQueryEditorSection
                    query={query}
                    setQuery={setQuery}
                    onRerun={() => dataNodeLogic.findMounted({ key: dataKey })?.actions.loadData('force_blocking')}
                    onUnrunTextChange={onUnrunTextChange}
                    surface="widget"
                />
            ) : (
                <LemonBanner type="info">
                    You can't edit the query of a metric widget yet. You can still change the tile title and
                    description.
                </LemonBanner>
            )}
            <div className="relative flex h-[320px] min-w-0 border rounded p-3" data-attr="metrics-widget-preview">
                <MetricsWidgetQueryPreview query={query} dataKey={dataKey} />
            </div>
        </div>
    )
}
