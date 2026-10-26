import { useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { MetricsQuery, MetricsQueryLanguage } from '~/queries/schema/schema-general'

import { queryLanguage } from '../queryLanguages/convert'
import { MetricsQueryEditor } from './MetricsQueryEditor'
import { MetricsQueryLanguagePicker } from './MetricsQueryLanguagePicker'
import { switchMetricsQueryLanguage } from './metricsQueryLanguageSwitch'
import { isBuilderCompatibleQuery } from './metricsViewerLogic'

let uniqueEditor = 0

// Only a builder query can draw a heatmap, so a switch to PromQL or SQL falls back to the default chart.
function withoutHeatmapDisplay(query: MetricsQuery): MetricsQuery {
    if (query.display?.type !== 'heatmap') {
        return query
    }
    const { type: _type, ...display } = query.display
    return { ...query, display }
}

/** The query editor of a saved metrics query: the builder / PromQL / SQL switch and the matching editor. */
export function MetricsQueryEditorSection({
    query,
    setQuery,
    onRerun,
    onUnrunTextChange,
    surface,
}: {
    query: MetricsQuery
    setQuery: (query: MetricsQuery) => void
    /** Runs the current PromQL or SQL query again when Run is pressed without a change, as after a failure. */
    onRerun?: () => void
    onUnrunTextChange?: (unrun: boolean) => void
    /** A widget offers every panel and the heatmap; an insight keeps the panels flag. */
    surface: 'insight' | 'widget'
}): JSX.Element {
    const languagesEnabled = useFeatureFlag('METRICS_QUERY_LANGUAGES')
    // A language switch replaces the query, so the editor remounts to seed its logic from the new one.
    const [editorKey, setEditorKey] = useState(() => `MetricsQueryEditor.${uniqueEditor++}`)

    const onSwitchLanguage = languagesEnabled
        ? (current: MetricsQuery, to: MetricsQueryLanguage): void =>
              switchMetricsQueryLanguage(current, to, (converted) => {
                  setQuery(to === 'builder' ? converted : withoutHeatmapDisplay(converted))
                  setEditorKey(`MetricsQueryEditor.${uniqueEditor++}`)
              })
        : undefined
    const language = queryLanguage(query)

    if (language !== 'builder' && !languagesEnabled) {
        return (
            <LemonBanner type="info" className="w-full">
                {`This ${surface} uses a ${language === 'promql' ? 'PromQL' : 'SQL'} query, which you can't edit here.`}
            </LemonBanner>
        )
    }

    if (language !== 'builder' || isBuilderCompatibleQuery(query)) {
        return (
            <MetricsQueryEditor
                key={editorKey}
                editorKey={editorKey}
                query={query}
                setQuery={setQuery}
                onSwitchLanguage={onSwitchLanguage}
                onRerun={onRerun}
                onUnrunTextChange={onUnrunTextChange}
                dataAttrPrefix={surface === 'widget' ? 'metrics-widget-editor' : 'metrics-query-editor'}
                allPanels={surface === 'widget'}
            />
        )
    }

    return (
        <div className="flex flex-col items-start gap-2">
            {onSwitchLanguage && (
                <MetricsQueryLanguagePicker value="builder" onChange={(to) => onSwitchLanguage(query, to)} />
            )}
            <LemonBanner type="info" className="w-full">
                {onSwitchLanguage
                    ? 'The builder cannot show this query. Switch to PromQL or SQL to edit it.'
                    : `This ${surface} uses settings that the builder cannot show, so the builder is off for this ${surface}.`}
            </LemonBanner>
        </div>
    )
}
