import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { setPromQLCompletionProvider } from 'lib/monaco/languages/promqlCompletionRegistry'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { objectsEqual } from 'lib/utils/objects'
import { teamLogic } from 'scenes/teamLogic'

import type { MetricsDisplayType, MetricsQuery, MetricsQueryLanguage } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { METRICS_PANELS } from '../panels/registry'
import { getPromQLCompletions } from '../queryLanguages/promqlCompletion'
import { createMetricsPromQLCompletionSource } from '../queryLanguages/promqlCompletionSource'
import { MetricsChartSettings } from './MetricsChartSettings'
import { MetricsClauseRow } from './MetricsClauseRow'
import { MetricsIntervalPicker } from './MetricsIntervalPicker'
import { METRICS_QUERY_LANGUAGE_LABELS } from './metricsQueryLanguageSwitch'
import { METRICS_DATE_OPTIONS, MetricsFormulaInput } from './MetricsViewer'
import { MAX_CLAUSES, metricsViewerLogic } from './metricsViewerLogic'

// The heatmap saves a different query kind, so the insight editor leaves it out.
const BASE_DISPLAY_TYPES: MetricsDisplayType[] = ['line', 'area', 'bar']
const PANEL_DISPLAY_TYPES: MetricsDisplayType[] = ['stat', 'gauge', 'bargauge', 'table']

const LANGUAGE_HINTS: Record<Exclude<MetricsQueryLanguage, 'builder'>, string> = {
    promql: 'Runs as a range query at the chart interval. Leave out the range, as in rate(x), to use the interval. Dashboard label filters do not apply.',
    sql: 'Return a time column and a value column. Other columns become series labels. Use {date_from}, {date_to}, {interval} and {interval_seconds} to follow the date range.',
}

export function MetricsQueryLanguagePicker({
    value,
    onChange,
    disabledReason,
}: {
    value: MetricsQueryLanguage
    onChange: (language: MetricsQueryLanguage) => void
    disabledReason?: string | null
}): JSX.Element {
    // PromQL runs through Snuffle, which has its own flag.
    const promqlEnabled = useFeatureFlag('LOGS_METRICS_SNUFFLE_API')
    return (
        <LemonSegmentedButton
            size="small"
            value={value}
            onChange={onChange}
            data-attr="metrics-query-language"
            options={(['builder', 'promql', 'sql'] as const).map((language) => ({
                value: language,
                label: METRICS_QUERY_LANGUAGE_LABELS[language],
                disabledReason:
                    disabledReason ??
                    (language === 'promql' && !promqlEnabled && value !== 'promql'
                        ? 'PromQL is not turned on for this project'
                        : undefined),
            }))}
        />
    )
}

/** The `/metrics` viewer's builder, editing a `MetricsQuery` in the insight editor. */
export function MetricsQueryEditor({
    editorKey,
    query,
    setQuery,
    onSwitchLanguage,
}: {
    editorKey: string
    query: MetricsQuery
    setQuery: (query: MetricsQuery) => void
    /** Shows the builder / PromQL / SQL switch. Gets the query as it is now, including an unrun draft. */
    onSwitchLanguage?: (current: MetricsQuery, to: MetricsQueryLanguage) => void
}): JSX.Element {
    // The query seeds the logic once. After that the builder only writes the query, so the two cannot loop.
    const logicProps = useMemo(() => ({ key: editorKey, initialQuery: query }), [editorKey]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <BindLogic logic={metricsViewerLogic} props={logicProps}>
            <MetricsQueryEditorControls query={query} setQuery={setQuery} onSwitchLanguage={onSwitchLanguage} />
        </BindLogic>
    )
}

function MetricsQueryTextEditor({
    language,
    disabledReason,
}: {
    language: Exclude<MetricsQueryLanguage, 'builder'>
    disabledReason: string | null
}): JSX.Element {
    const { queryDraft, queryTextChanged } = useValues(metricsViewerLogic)
    const { setQueryDraft, runQueryText } = useActions(metricsViewerLogic)
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
        <div className="flex flex-col gap-2 flex-1 min-w-[16rem]" data-attr={`metrics-query-editor-${language}`}>
            <CodeEditorResizeable
                // HogQL validation would flag the date placeholders, so SQL gets plain SQL highlighting.
                language={language === 'promql' ? 'promql' : 'sql'}
                value={queryDraft}
                onChange={(value) => setQueryDraft(value ?? '')}
                onPressCmdEnter={() => runQueryText()}
                minHeight={language === 'sql' ? '10rem' : '3rem'}
                maxHeight="24rem"
                options={{
                    readOnly: !!disabledReason,
                    minimap: { enabled: false },
                    wordWrap: 'on',
                    scrollBeyondLastLine: false,
                    lineNumbers: language === 'sql' ? 'on' : 'off',
                    // Label values and quoted OTel names are typed inside strings.
                    quickSuggestions: { other: true, comments: false, strings: true },
                }}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-secondary flex-1 min-w-[12rem]">{LANGUAGE_HINTS[language]}</span>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => runQueryText()}
                    disabledReason={disabledReason ?? (queryTextChanged ? undefined : 'Change the query to run it')}
                    data-attr={`metrics-query-editor-run-${language}`}
                >
                    Run
                </LemonButton>
            </div>
        </div>
    )
}

function MetricsQueryEditorControls({
    query,
    setQuery,
    onSwitchLanguage,
}: {
    query: MetricsQuery
    setQuery: (query: MetricsQuery) => void
    onSwitchLanguage?: (current: MetricsQuery, to: MetricsQueryLanguage) => void
}): JSX.Element {
    const { viewerClauses, activeClauseIndex, formula, namedClauses, dateFrom, dateTo, interval } =
        useValues(metricsViewerLogic)
    const { displayType, metricsQueryNode, language } = useValues(metricsViewerLogic)
    const { addClause, setDateFrom, setDateTo, setInterval, setDisplayType } = useActions(metricsViewerLogic)
    const logic = useMountedLogic(metricsViewerLogic)
    const dashboardPanelsEnabled = useFeatureFlag('METRICS_DASHBOARD_PANELS')
    const disabledReason = getAccessControlDisabledReason(AccessControlResourceType.Metrics, AccessControlLevel.Viewer)

    const switchLanguage = (to: MetricsQueryLanguage): void => {
        // Read the logic at click time, so a draft the user has not run yet still converts.
        const { metricsQueryNode: node, queryDraft } = logic.values
        const current = node ?? query
        onSwitchLanguage?.(language === 'builder' ? current : { ...current, [language]: queryDraft.trim() }, to)
    }

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

    // A formula result is ungrouped even when its input clauses group. PromQL and SQL results can have any labels.
    const resultIsGrouped =
        language !== 'builder' || (!formula && namedClauses.some((clause) => clause.groupByKeys.length > 0))
    const displayTypeOptions = useMemo(() => {
        const types = dashboardPanelsEnabled ? [...BASE_DISPLAY_TYPES, ...PANEL_DISPLAY_TYPES] : BASE_DISPLAY_TYPES
        return types.map((value) => {
            const def = METRICS_PANELS[value]
            return {
                value,
                label: def.label,
                disabledReason: def.needsGroupBy && !resultIsGrouped ? 'Add a group-by to use this panel' : undefined,
            }
        })
    }, [dashboardPanelsEnabled, resultIsGrouped])

    const showFormulaInput = viewerClauses.length > 1 || formula !== ''

    return (
        <div className="flex flex-col gap-2" data-attr="metrics-query-editor">
            {onSwitchLanguage && (
                <div>
                    <MetricsQueryLanguagePicker
                        value={language}
                        onChange={switchLanguage}
                        disabledReason={disabledReason}
                    />
                </div>
            )}
            <div className="flex flex-wrap items-start gap-2 justify-between">
                {language !== 'builder' ? (
                    <MetricsQueryTextEditor language={language} disabledReason={disabledReason} />
                ) : (
                    <div className="flex flex-col gap-2 flex-1 min-w-[16rem]">
                        {viewerClauses.map((clause, index) => (
                            <MetricsClauseRow
                                key={clause.name}
                                clause={clause}
                                index={index}
                                isActive={index === activeClauseIndex}
                                showAlias={viewerClauses.length > 1}
                                disabledReason={disabledReason}
                            />
                        ))}
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonButton
                                size="small"
                                type="secondary"
                                icon={<IconPlusSmall />}
                                onClick={() => addClause()}
                                disabledReason={
                                    disabledReason ??
                                    (viewerClauses.length >= MAX_CLAUSES
                                        ? `A query can have at most ${MAX_CLAUSES} series`
                                        : undefined)
                                }
                                data-attr="metrics-query-editor-add-series"
                            >
                                Add series
                            </LemonButton>
                            {showFormulaInput && <MetricsFormulaInput disabledReason={disabledReason} />}
                        </div>
                    </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                    <DateFilter
                        size="small"
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        dateOptions={METRICS_DATE_OPTIONS}
                        onChange={(changedDateFrom, changedDateTo) => {
                            setDateFrom(changedDateFrom)
                            setDateTo(changedDateTo)
                        }}
                        allowTimePrecision
                        allowFixedRangeWithTime
                        allowedRollingDateOptions={['minutes', 'hours', 'days', 'weeks']}
                        use24HourFormat
                        disabledReason={disabledReason}
                    />
                    <MetricsIntervalPicker value={interval} onChange={setInterval} disabledReason={disabledReason} />
                </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect
                    size="small"
                    value={displayType}
                    options={displayTypeOptions}
                    onChange={setDisplayType}
                    data-attr="metrics-query-editor-display-type"
                    disabledReason={disabledReason}
                />
                <MetricsChartSettings />
            </div>
        </div>
    )
}
