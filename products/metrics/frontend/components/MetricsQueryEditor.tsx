import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { setPromQLCompletionProvider } from 'lib/monaco/languages/promqlCompletionRegistry'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { DATE_TIME_FORMAT, formatDateRange } from 'lib/utils/datetime'
import { objectsEqual } from 'lib/utils/objects'
import { teamLogic } from 'scenes/teamLogic'

import {
    type MetricsDisplayType,
    type MetricsQuery,
    type MetricsQueryLanguage,
    NodeKind,
} from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, DateMappingOption } from '~/types'

import { METRICS_PANELS } from '../panels/registry'
import { getPromQLCompletions } from '../queryLanguages/promqlCompletion'
import { createMetricsPromQLCompletionSource } from '../queryLanguages/promqlCompletionSource'
import { MetricsChartSettings } from './MetricsChartSettings'
import { MetricsClauseRow } from './MetricsClauseRow'
import { MetricsIntervalPicker } from './MetricsIntervalPicker'
import { METRICS_QUERY_LANGUAGE_LABELS } from './metricsQueryLanguageSwitch'
import { MAX_CLAUSES, metricsViewerLogic, sanitizeFormulaInput } from './metricsViewerLogic'

// Mirrors the curated set used by `LogsViewer/Filters/DateRangeFilter`.
export const METRICS_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Last 5 minutes',
        values: ['-5M'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.subtract(5, 'minute').format(DATE_TIME_FORMAT),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 30 minutes',
        values: ['-30M'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.subtract(30, 'minute').format(DATE_TIME_FORMAT),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 1 hour',
        values: ['-1h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(1, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 24 hours',
        values: ['-24h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(24, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 7 days',
        values: ['-7d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(7, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
]

const BASE_DISPLAY_TYPES: MetricsDisplayType[] = ['line', 'area', 'bar']
const PANEL_DISPLAY_TYPES: MetricsDisplayType[] = ['stat', 'gauge', 'bargauge', 'table']

// Shown in an empty editor, so the expected shape is visible without help text.
const PLACEHOLDERS: Record<Exclude<MetricsQueryLanguage, 'builder'>, string> = {
    promql: 'sum by (service_name) (rate(http_requests_total))',
    sql: 'SELECT … AS time, … AS value FROM posthog.metrics WHERE timestamp >= {date_from}',
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

function MetricsQueryTextEditor({
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

export interface MetricsQueryControlsProps {
    /** Prefix of the `data-attr` of each control, so each surface keeps its own analytics names. */
    dataAttrPrefix: 'metrics-viewer' | 'metrics-query-editor'
    /** The query a language switch converts while the builder has no metric yet. */
    fallbackQuery?: MetricsQuery
    /** Shows the builder / PromQL / SQL switch. Gets the query as it is now, including an unrun draft. */
    onSwitchLanguage?: (current: MetricsQuery, to: MetricsQueryLanguage) => void
    /** Runs the current PromQL or SQL query again when Run is pressed without a change, as after a failure. */
    onRerun?: () => void
    /** Whether the result has labels. Without it, the builder's group-bys decide. */
    resultIsGrouped?: boolean
    /** Offers the heatmap display, which saves a histogram query instead of a time series. */
    heatmap?: { eligible: boolean }
    /** Controls after the date range and interval. */
    toolbarExtras?: ReactNode
    /** Controls after the display settings. */
    displayExtras?: ReactNode
    /** Buttons on the right of the display row. */
    actions?: ReactNode
}

/** The metrics query controls of the `/metrics` viewer and the metrics insight editor. */
export function MetricsQueryControls({
    dataAttrPrefix,
    fallbackQuery,
    onSwitchLanguage,
    onRerun,
    resultIsGrouped: resultIsGroupedProp,
    heatmap,
    toolbarExtras,
    displayExtras,
    actions,
}: MetricsQueryControlsProps): JSX.Element {
    const { viewerClauses, activeClauseIndex, formula, namedClauses, dateFrom, dateTo, interval } =
        useValues(metricsViewerLogic)
    const { displayType, language, queryDraft } = useValues(metricsViewerLogic)
    const { addClause, setDateFrom, setDateTo, setInterval, setDisplayType, runQueryText } =
        useActions(metricsViewerLogic)
    const logic = useMountedLogic(metricsViewerLogic)
    const dashboardPanelsEnabled = useFeatureFlag('METRICS_DASHBOARD_PANELS')
    const disabledReason = getAccessControlDisabledReason(AccessControlResourceType.Metrics, AccessControlLevel.Viewer)

    // A changed query runs through the query node. An unchanged one (after a failure) runs again in place.
    const runQuery = (): void => (logic.values.queryTextChanged ? runQueryText() : onRerun?.())

    const switchLanguage = (to: MetricsQueryLanguage): void => {
        // Read the logic at click time, so a draft the user has not run yet still converts.
        const { metricsQueryNode: node, queryDraft } = logic.values
        const current = node ?? fallbackQuery ?? { kind: NodeKind.MetricsQuery, clauses: [] }
        onSwitchLanguage?.(language === 'builder' ? current : { ...current, [language]: queryDraft.trim() }, to)
    }

    // A formula result is ungrouped even when its input clauses group. PromQL and SQL results can have any labels.
    const resultIsGrouped =
        resultIsGroupedProp ??
        (language !== 'builder' || (!formula && namedClauses.some((clause) => clause.groupByKeys.length > 0)))
    const displayTypeOptions = useMemo(() => {
        const types: MetricsDisplayType[] = dashboardPanelsEnabled
            ? [...BASE_DISPLAY_TYPES, ...PANEL_DISPLAY_TYPES, ...(heatmap ? (['heatmap'] as const) : [])]
            : BASE_DISPLAY_TYPES
        return types.map((value) => {
            const def = METRICS_PANELS[value]
            const reason = def.needsGroupBy
                ? !resultIsGrouped
                    ? 'Add a group-by to use this panel'
                    : undefined
                : def.needsHistogram && !heatmap?.eligible
                  ? 'Pick a single histogram metric (no formula) to use this panel'
                  : undefined
            return { value, label: def.label, disabledReason: reason }
        })
    }, [dashboardPanelsEnabled, resultIsGrouped, heatmap])

    const showFormulaInput = viewerClauses.length > 1 || formula !== ''

    const dateControls = (
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
            {toolbarExtras}
        </div>
    )

    const builderControls = (
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
                    data-attr={`${dataAttrPrefix}-add-series`}
                >
                    Add series
                </LemonButton>
                {showFormulaInput && <MetricsFormulaInput disabledReason={disabledReason} />}
            </div>
        </div>
    )

    return (
        <div className="flex flex-col gap-2" data-attr={dataAttrPrefix}>
            {onSwitchLanguage ? (
                <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <MetricsQueryLanguagePicker
                            value={language}
                            onChange={switchLanguage}
                            disabledReason={disabledReason}
                        />
                        {dateControls}
                    </div>
                    {language === 'builder' ? (
                        builderControls
                    ) : (
                        <MetricsQueryTextEditor language={language} disabledReason={disabledReason} onRun={runQuery} />
                    )}
                </>
            ) : (
                <div className="flex flex-wrap items-start gap-2 justify-between">
                    {builderControls}
                    {dateControls}
                </div>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonSelect
                        size="small"
                        value={displayType}
                        options={displayTypeOptions}
                        onChange={setDisplayType}
                        data-attr={`${dataAttrPrefix}-display-type`}
                        disabledReason={disabledReason}
                    />
                    <MetricsChartSettings />
                    {displayExtras}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    {actions}
                    {language !== 'builder' && (
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={runQuery}
                            disabledReason={disabledReason ?? (queryDraft.trim() ? undefined : 'Write a query first')}
                            data-attr={`metrics-query-editor-run-${language}`}
                        >
                            Run
                        </LemonButton>
                    )}
                </div>
            </div>
        </div>
    )
}

// Committed on blur/Enter (mirroring TrendsFormula) so a half-typed formula doesn't fire
// a query per keystroke. Input is lowercased — clause aliases are lowercase and the
// backend parser is case-sensitive.
export const MetricsFormulaInput = ({ disabledReason }: { disabledReason: string | null }): JSX.Element => {
    const { formula } = useValues(metricsViewerLogic)
    const { setFormula } = useActions(metricsViewerLogic)
    const [draft, setDraft] = useState(formula)

    // An external change (URL restore, clause reset) replaces the local draft.
    useEffect(() => {
        setDraft(formula)
    }, [formula])

    const commit = (): void => {
        if (draft !== formula) {
            setFormula(draft)
        }
    }

    return (
        <Tooltip title="Arithmetic over the series letters, with + - * / and parentheses. Only the formula result is charted.">
            <LemonInput
                size="small"
                className="min-w-48"
                value={draft}
                onChange={(value) => setDraft(sanitizeFormulaInput(value))}
                onBlur={commit}
                onPressEnter={commit}
                placeholder="Formula, e.g. (a - b) / a"
                data-attr="metrics-viewer-formula"
                disabledReason={disabledReason}
            />
        </Tooltip>
    )
}
