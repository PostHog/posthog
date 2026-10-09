import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonBanner, SpinnerOverlay } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { truncate } from 'lib/utils/strings'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AnyResponseType, MetricsQuery, MetricsQueryLanguage } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { MetricsQueryEditor, MetricsQueryLanguagePicker } from '../components/MetricsQueryEditor'
import { switchMetricsQueryLanguage } from '../components/metricsQueryLanguageSwitch'
import { isBuilderCompatibleQuery } from '../components/metricsViewerLogic'
import { MetricsPanel } from '../panels/MetricsPanel'
import { queryLanguage } from '../queryLanguages/convert'
import { seriesFromMetricsResponse } from './metricsResponseSeries'

let uniqueNode = 0
let uniqueEditor = 0

interface MetricsQueryNodeProps {
    query: MetricsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
    /** With `setQuery`, shows the builder above the chart, as the insight editor does. */
    editMode?: boolean
    setQuery?: (query: MetricsQuery) => void
}

/** Renders a `MetricsQuery` wherever the generic `Query` component is used —
 * saved insights, dashboard tiles, notebooks. */
const EMPTY_QUERY_MESSAGE: Record<MetricsQueryLanguage, string> = {
    builder: 'Pick a metric to see its time series.',
    promql: 'Run a query to see results.',
    sql: 'Run a query to see results.',
}

const queryText = (query: MetricsQuery): string =>
    (query.language === 'promql' ? query.promql : query.language === 'sql' ? query.sql : '') ?? ''

export function MetricsQueryNode(props: MetricsQueryNodeProps): JSX.Element | null {
    const builderEnabled = useFeatureFlag('METRICS_INSIGHT_BUILDER')
    const languagesEnabled = useFeatureFlag('METRICS_QUERY_LANGUAGES')
    // A language switch replaces the query, so the editor remounts to seed its logic from the new one.
    const [editorKey, setEditorKey] = useState(() => `MetricsQueryEditor.${uniqueEditor++}`)
    const language = queryLanguage(props.query)

    // A new insight starts with no clauses, which the backend rejects, so there is nothing to run yet.
    const hasQuery = language === 'builder' ? props.query.clauses.length > 0 : queryText(props.query).trim() !== ''
    const results = hasQuery ? (
        <MetricsQueryResults {...props} />
    ) : (
        <div className="flex-1 flex items-center justify-center min-h-[200px] text-secondary text-sm">
            {EMPTY_QUERY_MESSAGE[language]}
        </div>
    )

    if (!builderEnabled || !props.editMode || !props.setQuery) {
        return results
    }

    const setQuery = props.setQuery
    const onSwitchLanguage = languagesEnabled
        ? (current: MetricsQuery, to: MetricsQueryLanguage): void =>
              switchMetricsQueryLanguage(current, to, (converted) => {
                  setQuery(converted)
                  setEditorKey(`MetricsQueryEditor.${uniqueEditor++}`)
              })
        : undefined

    return (
        <div className="flex flex-col gap-3 w-full">
            {language !== 'builder' || isBuilderCompatibleQuery(props.query) ? (
                <MetricsQueryEditor
                    key={editorKey}
                    editorKey={editorKey}
                    query={props.query}
                    setQuery={setQuery}
                    onSwitchLanguage={onSwitchLanguage}
                />
            ) : (
                <div className="flex flex-col items-start gap-2">
                    {onSwitchLanguage && (
                        <MetricsQueryLanguagePicker
                            value="builder"
                            onChange={(to) => onSwitchLanguage(props.query, to)}
                        />
                    )}
                    <LemonBanner type="info" className="w-full">
                        {onSwitchLanguage
                            ? 'The builder cannot show this query. Switch to PromQL or SQL to edit it.'
                            : 'This insight uses settings that the builder cannot show, so the builder is off for this insight.'}
                    </LemonBanner>
                </div>
            )}
            <div className="relative flex h-[360px] border rounded p-3">{results}</div>
        </div>
    )
}

function MetricsQueryResults(props: MetricsQueryNodeProps): JSX.Element {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `MetricsQueryNode.${uniqueNode++}`)
    // `dataNodeLogic` deep-compares its query to decide whether to refetch. Its
    // `ignoreVisualizationOnlyChanges` option doesn't help here — that only reaches
    // `cleanInsightQuery`, which bails unless both sides are insight query nodes, and a
    // `MetricsQuery` isn't one. So chart settings have to be kept out of the query it sees,
    // or changing the chart type would re-run the ClickHouse query.
    const dataQuery = useMemo(() => {
        const { display: _display, ...rest } = props.query
        return rest
    }, [props.query])
    const logic = dataNodeLogic({
        query: dataQuery,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    useAttachedLogic(logic, props.attachTo)

    const { response, responseLoading, responseError } = useValues(logic)
    const series = seriesFromMetricsResponse(response)
    const hasPoints = series.some((s) => s.points.length > 0)
    // A formula query returns only the formula result (metricName is null on it),
    // so the formula text itself is the honest name for an unlabelled series.
    const fallbackName =
        props.query.formula ??
        props.query.clauses[0]?.metricName ??
        (props.query.language === 'promql' && props.query.promql ? truncate(props.query.promql, 80) : 'metric')

    return (
        <div className="relative flex flex-col w-full h-full min-h-[200px]">
            {responseError && !responseLoading ? (
                <div className="flex-1 flex items-center p-4 min-w-0">
                    <LemonBanner type="error" className="w-full">
                        {responseError}
                    </LemonBanner>
                </div>
            ) : hasPoints ? (
                <MetricsPanel series={series} fallbackName={fallbackName} display={props.query.display} />
            ) : !responseLoading ? (
                <div className="flex-1 flex items-center justify-center text-secondary text-sm">
                    No data for this metric in the selected range.
                </div>
            ) : null}
            {responseLoading && <SpinnerOverlay />}
        </div>
    )
}
