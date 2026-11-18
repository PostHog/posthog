import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { setPromQLCompletionProvider } from 'lib/monaco/languages/promqlCompletionRegistry'
import { teamLogic } from 'scenes/teamLogic'

import { type MetricsQueryLanguage } from '~/queries/schema/schema-general'

import { getPromQLCompletions } from '../queryLanguages/promqlCompletion'
import { createMetricsPromQLCompletionSource } from '../queryLanguages/promqlCompletionSource'
import { metricsViewerLogic } from './metricsViewerLogic'

// Shown in an empty editor, so the expected shape is visible without help text.
const PLACEHOLDERS: Record<Exclude<MetricsQueryLanguage, 'builder'>, string> = {
    promql: 'sum by (service_name) (rate(http_requests_total))',
    sql: 'SELECT … AS time, … AS value FROM posthog.metrics WHERE timestamp >= {date_from}',
}

export function MetricsQueryTextEditor({
    language,
    disabledReason,
    onRun,
}: {
    language: Exclude<MetricsQueryLanguage, 'builder'>
    disabledReason: string | null
    onRun: () => void
}): JSX.Element {
    const { queryDraft } = useValues(metricsViewerLogic)
    const { setQueryDraft } = useActions(metricsViewerLogic)
    const { currentTeamId } = useValues(teamLogic)

    useEffect(() => {
        if (language !== 'promql' || !currentTeamId) {
            return
        }
        const source = createMetricsPromQLCompletionSource(String(currentTeamId))
        // Load the metric names now, so the first suggestions do not wait for them.
        void source.metricNames('').catch(() => undefined)
        return setPromQLCompletionProvider((text, offset) => getPromQLCompletions(text, offset, source))
    }, [language, currentTeamId])

    return (
        <div className="w-full" data-attr={`metrics-query-editor-${language}`}>
            <CodeEditorResizeable
                // HogQL validation would flag the date placeholders, so SQL gets plain SQL highlighting.
                language={language === 'promql' ? 'promql' : 'sql'}
                value={queryDraft}
                onChange={(value) => setQueryDraft(value ?? '')}
                onPressCmdEnter={onRun}
                minHeight={language === 'sql' ? '8rem' : '2.5rem'}
                maxHeight="24rem"
                options={{
                    readOnly: !!disabledReason,
                    placeholder: PLACEHOLDERS[language],
                    minimap: { enabled: false },
                    wordWrap: 'on',
                    scrollBeyondLastLine: false,
                    lineNumbers: language === 'sql' ? 'on' : 'off',
                    folding: false,
                    glyphMargin: false,
                    lineDecorationsWidth: 10,
                    overviewRulerLanes: 0,
                    hideCursorInOverviewRuler: true,
                    renderLineHighlight: 'none',
                    padding: { top: 6, bottom: 6 },
                    scrollbar: { useShadows: false, verticalScrollbarSize: 8, alwaysConsumeMouseWheel: false },
                    // Label values and quoted OTel names are typed inside strings.
                    quickSuggestions: { other: true, comments: false, strings: true },
                }}
            />
        </div>
    )
}
