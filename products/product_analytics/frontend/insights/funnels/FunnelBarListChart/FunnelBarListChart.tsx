import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { type ErrorInfo, useMemo } from 'react'

import { type PointClickData, StackedBarList, type TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'

import { groupsModel } from '~/models/groupsModel'
import { AvailableFeature, type ChartParams, type FunnelStepWithConversionMetrics, StepOrderValue } from '~/types'

import { FunnelBarHorizontalTooltip } from '../FunnelBarHorizontalChart/FunnelBarHorizontalTooltip'
import {
    buildFunnelBarHorizontalCompareData,
    buildFunnelBarHorizontalData,
    FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN,
    type FunnelBarHorizontalSegmentMeta,
    type FunnelBarHorizontalStepData,
    mergeFunnelBarHorizontalRows,
} from '../FunnelBarHorizontalChart/funnelBarHorizontalTransforms'
import { GlyphColumn } from '../FunnelBarHorizontalChart/GlyphColumn'
import { openFunnelSegmentPersons } from '../FunnelBarHorizontalChart/openFunnelSegmentPersons'
import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { FunnelBarListDropOff } from './FunnelBarListDropOff'
import { FunnelBarListLabel } from './FunnelBarListLabel'
import { FunnelBarListValue } from './FunnelBarListValue'

interface FunnelBarListRow {
    stepIndex: number
    bar: FunnelBarHorizontalStepData
    /** Set only in compare mode. */
    period?: 'current' | 'previous'
}

const BAR_HEIGHT = 24
// Leaves more space above each label than below it, so the label reads as part of its own bar.
const ROW_HEIGHT = 56
// Transparent so the track shows through, but kept for hover, tooltip and click routing.
const DROP_OFF_COLOR = 'transparent'

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'funnels-bar-list-chart',
        componentStack: info.componentStack ?? undefined,
    })
}

export function FunnelBarListChart({ showPersonsModal: showPersonsModalProp = true }: ChartParams): JSX.Element | null {
    const theme = useChartTheme()
    const { insightProps } = useValues(insightLogic)
    const {
        visibleStepsWithConversionMetrics: steps,
        funnelsFilter,
        breakdownFilter,
        isStepOptional,
        getFunnelsColor,
        querySource,
        isComparedFunnel,
        insightData,
        hasPartialBreakdownSelection,
        aggregationTargetLabel,
    } = useValues(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForStep, openPersonsModalForSeries } = useActions(funnelPersonsModalLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)
    const { hasAvailableFeature } = useValues(userLogic)

    const showPersonsModal = canOpenPersonModal && showPersonsModalProp
    const isUnordered = funnelsFilter?.funnelOrderType === StepOrderValue.UNORDERED
    const groupTypeLabel = aggregationLabel(querySource?.aggregation_group_type_index).plural
    // Paths are user-based, so there is nothing to link to when aggregating by groups.
    const showStepPaths =
        hasAvailableFeature(AvailableFeature.PATHS_ADVANCED) && querySource?.aggregation_group_type_index == null

    const rows = useMemo<FunnelBarListRow[]>(() => {
        const options = {
            breakdownFilter,
            getColor: getFunnelsColor,
            getLabel: (variant: FunnelStepWithConversionMetrics) =>
                String(variant.breakdown_value ?? variant.name ?? ''),
            fillerColor: DROP_OFF_COLOR,
        }
        if (!isComparedFunnel) {
            return buildFunnelBarHorizontalData(steps, options).map((bar, stepIndex) => ({ stepIndex, bar }))
        }
        return buildFunnelBarHorizontalCompareData(steps, options).flatMap((step, stepIndex) =>
            step.bars.map((bar, barIndex) => ({ stepIndex, bar, period: barIndex === 0 ? 'current' : 'previous' }))
        )
    }, [steps, breakdownFilter, getFunnelsColor, isComparedFunnel])
    const labels = useMemo(() => rows.map((row) => `${row.stepIndex}:${row.period ?? 'all'}`), [rows])
    const series = useMemo(() => mergeFunnelBarHorizontalRows(rows.map((row) => row.bar)), [rows])
    const rowKeys = useMemo(() => rows.map((row) => new Set(row.bar.series.map((s) => s.key))), [rows])

    if (steps.length === 0) {
        return null
    }

    // The merged chart holds every row's segments, so narrow the tooltip to this row's.
    const renderTooltip = (ctx: TooltipContext<FunnelBarHorizontalSegmentMeta>): JSX.Element | null => {
        const row = rows[ctx.dataIndex]
        if (!row) {
            return null
        }
        const rowContext = {
            ...ctx,
            seriesData: ctx.seriesData
                .filter((entry) => rowKeys[ctx.dataIndex].has(entry.series.key))
                .map((entry) => {
                    const bar = entry.series.bars?.[ctx.dataIndex]
                    return {
                        ...entry,
                        color: bar?.color ?? entry.color,
                        series: { ...entry.series, meta: bar?.meta ?? entry.series.meta },
                    }
                }),
        }
        return (
            <FunnelBarHorizontalTooltip
                context={rowContext}
                step={steps[row.stepIndex]}
                stepIndex={row.stepIndex}
                firstStep={steps[0]}
                breakdownFilter={breakdownFilter}
                isPartialBreakdownSelection={hasPartialBreakdownSelection}
                groupTypeLabel={groupTypeLabel}
                showPersonsModal={showPersonsModal}
                resolvedDateRange={insightData?.resolved_date_range}
                compareTo={querySource?.compareFilter?.compare_to}
            />
        )
    }

    const onPointClick = showPersonsModal
        ? ({ series: clicked, dataIndex }: PointClickData<FunnelBarHorizontalSegmentMeta>): void => {
              const row = rows[dataIndex]
              const meta = clicked.bars?.[dataIndex]?.meta ?? clicked.meta
              if (row && meta) {
                  openFunnelSegmentPersons(steps[row.stepIndex], meta, isComparedFunnel, {
                      openPersonsModalForStep,
                      openPersonsModalForSeries,
                  })
              }
          }
        : undefined

    return (
        <div data-attr="funnel-bar-list" className="flex w-full gap-2 p-4">
            {/* Each step's first label line starts at the top of its rows, so the ring sits beside the label and bar. */}
            <div className="shrink-0 pt-2.5">
                {steps.map((step, stepIndex) => (
                    <div
                        key={step.order}
                        className={clsx('flex', isStepOptional(stepIndex + 1) && 'opacity-60')}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: rows.filter((row) => row.stepIndex === stepIndex).length * ROW_HEIGHT }}
                    >
                        <GlyphColumn
                            index={stepIndex}
                            stepCount={steps.length}
                            glyphNumber={step.order + 1}
                            isUnordered={isUnordered}
                            isOptional={false}
                            hasOptionalSteps={false}
                        />
                    </div>
                ))}
            </div>
            <div className="@container min-w-0 flex-1">
                <StackedBarList
                    labels={labels}
                    series={series}
                    theme={theme}
                    config={{
                        labelPosition: 'top',
                        rowHeight: ROW_HEIGHT,
                        barHeight: BAR_HEIGHT,
                        valueDomain: FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN,
                    }}
                    renderLabel={(rowIndex) => (
                        <>
                            <FunnelBarListLabel
                                step={steps[rows[rowIndex].stepIndex]}
                                stepIndex={rows[rowIndex].stepIndex}
                                period={rows[rowIndex].period}
                                isUnordered={isUnordered}
                                isOptional={isStepOptional(rows[rowIndex].stepIndex + 1)}
                                showStepPaths={showStepPaths}
                            />
                            <span className="ml-1 shrink-0 whitespace-nowrap text-sm leading-4">
                                <FunnelBarListValue
                                    step={steps[rows[rowIndex].stepIndex]}
                                    firstStep={steps[0]}
                                    period={rows[rowIndex].period}
                                    aggregationTargetLabel={aggregationTargetLabel}
                                />
                            </span>
                        </>
                    )}
                    renderValue={(rowIndex) => (
                        <FunnelBarListDropOff
                            step={steps[rows[rowIndex].stepIndex]}
                            stepIndex={rows[rowIndex].stepIndex}
                            period={rows[rowIndex].period}
                            aggregationTargetLabel={aggregationTargetLabel}
                        />
                    )}
                    tooltip={renderTooltip}
                    onPointClick={onPointClick}
                    onError={handleChartError}
                />
            </div>
        </div>
    )
}
