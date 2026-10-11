import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { type ErrorInfo, useMemo } from 'react'

import { IconInfinity } from '@posthog/icons'
import { type PointClickData, StackedBarList, type TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { insightLogic } from 'scenes/insights/insightLogic'

import { groupsModel } from '~/models/groupsModel'
import { type ChartParams, type FunnelStepWithConversionMetrics, StepOrderValue } from '~/types'

import { DuplicateStepIndicator } from '../FunnelBarHorizontalChart/DuplicateStepIndicator'
import { FunnelBarHorizontalTooltip } from '../FunnelBarHorizontalChart/FunnelBarHorizontalTooltip'
import {
    buildFunnelBarHorizontalCompareData,
    buildFunnelBarHorizontalData,
    FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN,
    type FunnelBarHorizontalSegmentMeta,
    type FunnelBarHorizontalStepData,
    mergeFunnelBarHorizontalRows,
    periodTotals,
} from '../FunnelBarHorizontalChart/funnelBarHorizontalTransforms'
import { openFunnelSegmentPersons } from '../FunnelBarHorizontalChart/openFunnelSegmentPersons'
import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { funnelConversionRate } from '../shared/funnelBarHorizontalShared'
import { FunnelStepMore } from '../shared/FunnelStepMore'
import { getActionFilterFromFunnelStep } from '../shared/funnelStepTableUtils'

interface FunnelBarListRow {
    stepIndex: number
    bar: FunnelBarHorizontalStepData
    /** Compare mode only: the period that this row's bar shows. */
    period?: 'current' | 'previous'
}

// Tall enough for the 23px step glyph.
const ROW_HEIGHT = 32
// The drop-off segment stays for hover, tooltip and click routing, but it is transparent so the
// list's neutral track shows through, as on every other bar list.
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

    // The merged chart lists every row's segments, so narrow the tooltip to this row's own segments
    // with this row's meta. The funnel tooltip then reads the hover as it does for a one-step chart.
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

    const renderLabel = (rowIndex: number): JSX.Element => {
        const { stepIndex, period } = rows[rowIndex]
        if (period === 'previous') {
            // Lines up with the step name after the 23px glyph and the 6px cell gap.
            return <span className="truncate pl-[29px] text-secondary">Previous period</span>
        }
        const step = steps[stepIndex]
        const isOptional = isStepOptional(stepIndex + 1)
        const isDuplicate = !isUnordered && stepIndex > 0 && step.action_id === steps[stepIndex - 1].action_id
        return (
            <>
                <span className="shrink-0 select-none">
                    <SeriesGlyph variant="funnel-step-glyph">
                        {isUnordered ? <IconInfinity className="w-3.5 fill-[var(--primary_alt)]" /> : step.order + 1}
                    </SeriesGlyph>
                </span>
                <span className={clsx('min-w-0 truncate font-semibold', isOptional && 'opacity-60')}>
                    {isUnordered ? (
                        `Completed ${step.order + 1} steps`
                    ) : (
                        <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
                    )}
                </span>
                {/* A narrow list keeps the room for the step name, and the dimmed name still marks the step. */}
                {isOptional ? <span className="shrink-0 text-secondary @max-md:hidden">(optional)</span> : null}
                {isDuplicate ? <DuplicateStepIndicator /> : null}
                <FunnelStepMore stepIndex={stepIndex} />
            </>
        )
    }

    // A compare row shows its own period's conversion, because its bar is scaled to the larger
    // period's first step and would not read as a conversion rate.
    const renderValue = (rowIndex: number): JSX.Element => {
        const { stepIndex, period } = rows[rowIndex]
        const step = steps[stepIndex]
        const count = period ? periodTotals(step)[period] : step.count
        const rate = period
            ? funnelConversionRate(count, periodTotals(steps[0])[period])
            : step.conversionRates.fromBasisStep
        // A narrow list drops the count, as a bar list does, and the tooltip still shows it.
        return (
            <>
                {percentage(rate, 1)}
                <span className="@max-md:hidden"> · {humanFriendlyNumber(count)}</span>
            </>
        )
    }

    return (
        <div data-attr="funnel-bar-list" className="w-full p-4">
            <StackedBarList
                labels={labels}
                series={series}
                theme={theme}
                config={{ rowHeight: ROW_HEIGHT, valueDomain: FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN }}
                renderLabel={renderLabel}
                renderValue={renderValue}
                tooltip={renderTooltip}
                onPointClick={onPointClick}
                onError={handleChartError}
            />
        </div>
    )
}
