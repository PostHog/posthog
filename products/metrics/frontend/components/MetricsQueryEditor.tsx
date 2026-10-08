import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { objectsEqual } from 'lib/utils/objects'

import type { MetricsDisplayType, MetricsQuery } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { METRICS_PANELS } from '../panels/registry'
import { MetricsChartSettings } from './MetricsChartSettings'
import { MetricsClauseRow } from './MetricsClauseRow'
import { MetricsIntervalPicker, MetricsMinIntervalPicker } from './MetricsIntervalPicker'
import { METRICS_DATE_OPTIONS, MetricsFormulaInput } from './MetricsViewer'
import { MAX_CLAUSES, metricsViewerLogic } from './metricsViewerLogic'

// The heatmap saves a different query kind, so the insight editor leaves it out.
const BASE_DISPLAY_TYPES: MetricsDisplayType[] = ['line', 'area', 'bar']
const PANEL_DISPLAY_TYPES: MetricsDisplayType[] = ['stat', 'gauge', 'bargauge', 'table']

/** The `/metrics` viewer's builder, editing a `MetricsQuery` in the insight editor. */
export function MetricsQueryEditor({
    editorKey,
    query,
    setQuery,
}: {
    editorKey: string
    query: MetricsQuery
    setQuery: (query: MetricsQuery) => void
}): JSX.Element {
    // The query seeds the logic once. After that the builder only writes the query, so the two cannot loop.
    const logicProps = useMemo(() => ({ key: editorKey, initialQuery: query }), [editorKey]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <BindLogic logic={metricsViewerLogic} props={logicProps}>
            <MetricsQueryEditorControls query={query} setQuery={setQuery} />
        </BindLogic>
    )
}

function MetricsQueryEditorControls({
    query,
    setQuery,
}: {
    query: MetricsQuery
    setQuery: (query: MetricsQuery) => void
}): JSX.Element {
    const { viewerClauses, activeClauseIndex, formula, namedClauses, dateFrom, dateTo, interval, minInterval } =
        useValues(metricsViewerLogic)
    const { displayType, metricsQueryNode } = useValues(metricsViewerLogic)
    const { addClause, setDateFrom, setDateTo, setInterval, setMinInterval, setDisplayType } =
        useActions(metricsViewerLogic)
    const dashboardPanelsEnabled = useFeatureFlag('METRICS_DASHBOARD_PANELS')
    const disabledReason = getAccessControlDisabledReason(AccessControlResourceType.Metrics, AccessControlLevel.Viewer)

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
        const { formula: _formula, interval: _interval, minInterval: _minInterval, display: _display, ...rest } = query
        setQuery({ ...rest, ...metricsQueryNode })
    }, [metricsQueryNode]) // eslint-disable-line react-hooks/exhaustive-deps

    // A formula result is ungrouped even when its input clauses group.
    const resultIsGrouped = !formula && namedClauses.some((clause) => clause.groupByKeys.length > 0)
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
            <div className="flex flex-wrap items-start gap-2 justify-between">
                <div className="flex flex-col gap-2 flex-1 min-w-[16rem]">
                    {viewerClauses.map((clause, index) => (
                        <MetricsClauseRow
                            key={clause.name}
                            clause={clause}
                            index={index}
                            isActive={index === activeClauseIndex}
                            showAlias={viewerClauses.length > 1}
                            showExplain={false}
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
                    <MetricsMinIntervalPicker
                        value={minInterval}
                        onChange={setMinInterval}
                        disabledReason={disabledReason}
                    />
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
