import { BindLogic, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { objectsEqual } from 'lib/utils/objects'

import type { MetricsQuery, MetricsQueryLanguage } from '~/queries/schema/schema-general'

import type { MetricsQueryControlsProps } from './MetricsQueryControls'
import { MetricsQueryEditorControls } from './MetricsQueryEditorControls'
import { metricsViewerLogic } from './metricsViewerLogic'

/** The `/metrics` viewer's builder, editing a `MetricsQuery` in the insight editor or a metric widget. */
export function MetricsQueryEditor({
    editorKey,
    query,
    setQuery,
    onSwitchLanguage,
    onRerun,
    dataAttrPrefix = 'metrics-query-editor',
    allPanels,
    onUnrunTextChange,
}: {
    editorKey: string
    query: MetricsQuery
    setQuery: (query: MetricsQuery) => void
    /** Shows the builder / PromQL / SQL switch. Gets the query as it is now, including an unrun draft. */
    onSwitchLanguage?: (current: MetricsQuery, to: MetricsQueryLanguage) => void
    /** Runs the current PromQL or SQL query again when Run is pressed without a change, as after a failure. */
    onRerun?: () => void
    dataAttrPrefix?: MetricsQueryControlsProps['dataAttrPrefix']
    /** Offers every panel, the heatmap included, whatever the panels flag says. */
    allPanels?: boolean
    /** Gets whether the PromQL or SQL editor holds text that has not run yet, so it is not in `query`. */
    onUnrunTextChange?: (unrun: boolean) => void
}): JSX.Element {
    // The query seeds the logic once. After that the builder only writes the query, so the two cannot loop.
    const logicProps = useMemo(() => ({ key: editorKey, initialQuery: query }), [editorKey]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <BindLogic logic={metricsViewerLogic} props={logicProps}>
            <MetricsQuerySync query={query} setQuery={setQuery} />
            {onUnrunTextChange ? <MetricsQueryUnrunTextReporter onChange={onUnrunTextChange} /> : null}
            <MetricsQueryEditorControls
                dataAttrPrefix={dataAttrPrefix}
                fallbackQuery={query}
                onSwitchLanguage={onSwitchLanguage}
                onRerun={onRerun}
                allPanels={allPanels}
            />
        </BindLogic>
    )
}

function MetricsQueryUnrunTextReporter({ onChange }: { onChange: (unrun: boolean) => void }): null {
    const { queryTextChanged } = useValues(metricsViewerLogic)
    useEffect(() => onChange(queryTextChanged), [queryTextChanged]) // eslint-disable-line react-hooks/exhaustive-deps
    return null
}

/** Writes the builder's query back to the insight as it changes. */
function MetricsQuerySync({ query, setQuery }: { query: MetricsQuery; setQuery: (query: MetricsQuery) => void }): null {
    const { metricsQueryNode } = useValues(metricsViewerLogic)
    // The node the saved query maps to. Until the first edit, a node equal to it is not written back,
    // so opening the editor does not mark the insight as changed.
    const seedNode = useRef(metricsQueryNode)
    const edited = useRef(false)
    useEffect(() => {
        if (!metricsQueryNode || (!edited.current && objectsEqual(metricsQueryNode, seedNode.current))) {
            return
        }
        edited.current = true
        // Keep node fields the builder does not own; drop the optional ones it does, so clearing them sticks.
        const {
            formula: _formula,
            interval: _interval,
            display: storedDisplay,
            language: _language,
            promql: _promql,
            sql: _sql,
            ...rest
        } = query
        // The same goes for display settings: thresholds or a unit from an import or the API survive an edit.
        const {
            type: _type,
            goalLines: _goalLines,
            yAxis: _yAxis,
            reduce: _reduce,
            statSummary: _statSummary,
            ...displayNotOwnedByBuilder
        } = storedDisplay ?? {}
        const display = { ...displayNotOwnedByBuilder, ...metricsQueryNode.display }
        setQuery({ ...rest, ...metricsQueryNode, ...(Object.keys(display).length ? { display } : {}) })
    }, [metricsQueryNode]) // eslint-disable-line react-hooks/exhaustive-deps
    return null
}
