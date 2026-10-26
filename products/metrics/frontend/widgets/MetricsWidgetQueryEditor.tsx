import { useState } from 'react'

import type { MetricsQuery } from '~/queries/schema/schema-general'

import { MetricsQueryEditorSection } from '../components/MetricsQueryEditorSection'
import { MetricsWidgetQueryPreview } from './MetricsWidgetQueryPreview'

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
    // Run on an unchanged PromQL or SQL query (after a failure, say) remounts the preview, which queries again.
    const [previewRun, setPreviewRun] = useState(0)

    return (
        <div className="flex flex-col gap-3 min-w-0">
            <MetricsQueryEditorSection
                query={query}
                setQuery={setQuery}
                onRerun={() => setPreviewRun((run) => run + 1)}
                onUnrunTextChange={onUnrunTextChange}
                surface="widget"
            />
            <div className="relative flex h-[320px] min-w-0 border rounded p-3" data-attr="metrics-widget-preview">
                <MetricsWidgetQueryPreview key={previewRun} query={query} />
            </div>
        </div>
    )
}
