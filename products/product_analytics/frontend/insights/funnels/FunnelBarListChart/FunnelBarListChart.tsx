import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { type ErrorInfo, useMemo } from 'react'

import { type PointClickData, StackedBarList, type TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { insightLogic } from 'scenes/insights/insightLogic'

import { groupsModel } from '~/models/groupsModel'
import { type ChartParams, type FunnelStepWithConversionMetrics, StepOrderValue } from '~/types'

import { FunnelBarHorizontalTooltip } from '../FunnelBarHorizontalChart/FunnelBarHorizontalTooltip'
import {
    buildFunnelBarHorizontalCompareData,
    buildFunnelBarHorizontalData,
    FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN,
    type FunnelBarHorizontalSegmentMeta,
    type FunnelBarHorizontalStepData,
    mergeFunnelBarHorizontalRows,
} from '../FunnelBarHorizontalChart/funnelBarHorizontalTransforms'
import { openFunnelSegmentPersons } from '../FunnelBarHorizontalChart/openFunnelSegmentPersons'
import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { FunnelBarListLabel } from './FunnelBarListLabel'
import { FunnelBarListValue } from './FunnelBarListValue'

interface FunnelBarListRow {
    stepIndex: number
    bar: FunnelBarHorizontalStepData
    /** Set only in compare mode. */
    period?: 'current' | 'previous'
}

// Tall enough for the 23px step glyph.
const ROW_HEIGHT = 32
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
    } = useValues(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForStep, openPersonsModalForSeries } = useActions(funnelPersonsModalLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const showPersonsModal = canOpenPersonModal && showPersonsModalProp
    const isUnordered = funnelsFilter?.funnelOrderType === StepOrderValue.UNORDERED
    const groupTypeLabel = aggregationLabel(querySource?.aggregation_group_type_index).plural

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
        <div data-attr="funnel-bar-list" className="w-full p-4">
            <StackedBarList
                labels={labels}
                series={series}
                theme={theme}
                config={{ rowHeight: ROW_HEIGHT, valueDomain: FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN }}
                renderLabel={(rowIndex) => (
                    <FunnelBarListLabel
                        step={steps[rows[rowIndex].stepIndex]}
                        previousStep={steps[rows[rowIndex].stepIndex - 1]}
                        stepIndex={rows[rowIndex].stepIndex}
                        period={rows[rowIndex].period}
                        isUnordered={isUnordered}
                        isOptional={isStepOptional(rows[rowIndex].stepIndex + 1)}
                    />
                )}
                renderValue={(rowIndex) => (
                    <FunnelBarListValue
                        step={steps[rows[rowIndex].stepIndex]}
                        firstStep={steps[0]}
                        period={rows[rowIndex].period}
                    />
                )}
                tooltip={renderTooltip}
                onPointClick={onPointClick}
                onError={handleChartError}
            />
        </div>
    )
}
