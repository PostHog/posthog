import { BindLogic, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { objectsEqual } from 'lib/utils/objects'

import type { MetricsQuery, MetricsQueryLanguage } from '~/queries/schema/schema-general'

import { MetricsQueryControls } from './MetricsQueryControls'
import { metricsViewerLogic } from './metricsViewerLogic'

/** The `/metrics` viewer's builder, editing a `MetricsQuery` in the insight editor. */
export function MetricsQueryEditor({
    editorKey,
    query,
    setQuery,
    onSwitchLanguage,
    onRerun,
}: {
    editorKey: string
    query: MetricsQuery
    setQuery: (query: MetricsQuery) => void
    /** Shows the builder / PromQL / SQL switch. Gets the query as it is now, including an unrun draft. */
    onSwitchLanguage?: (current: MetricsQuery, to: MetricsQueryLanguage) => void
    /** Runs the current PromQL or SQL query again when Run is pressed without a change, as after a failure. */
    onRerun?: () => void
}): JSX.Element {
    // The query seeds the logic once. After that the builder only writes the query, so the two cannot loop.
    const logicProps = useMemo(() => ({ key: editorKey, initialQuery: query }), [editorKey]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <BindLogic logic={metricsViewerLogic} props={logicProps}>
            <MetricsQuerySync query={query} setQuery={setQuery} />
            <MetricsQueryControls
                dataAttrPrefix="metrics-query-editor"
                fallbackQuery={query}
                onSwitchLanguage={onSwitchLanguage}
                onRerun={onRerun}
            />
        </BindLogic>
    )
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
            display: _display,
            language: _language,
            promql: _promql,
            sql: _sql,
            ...rest
        } = query
        setQuery({ ...rest, ...metricsQueryNode })
    }, [metricsQueryNode]) // eslint-disable-line react-hooks/exhaustive-deps
    return null
}
