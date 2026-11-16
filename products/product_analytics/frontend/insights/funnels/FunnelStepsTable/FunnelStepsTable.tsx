import { useActions, useValues } from 'kea'
import { compare as compareFn } from 'natural-orderby'

import { IconFlag } from '@posthog/icons'
import { LemonColorButton, LemonTag } from '@posthog/lemon-ui'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { LemonTable, LemonTableColumn, LemonTableColumnGroup } from 'lib/lemon-ui/LemonTable'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { resultCustomizationsModalLogic } from '~/queries/nodes/InsightViz/resultCustomizationsModalLogic'
import { FlattenedFunnelStepByBreakdown } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { getVisibilityKey } from '../funnelUtils'
import { getFunnelStepEntity } from '../shared/funnelStepSeries'
import { getSignificanceFromBreakdownStep } from '../shared/funnelStepTableUtils'
import { ValueInspectorButton } from '../shared/ValueInspectorButton'
import { QuillFunnelStepsTable } from './QuillFunnelStepsTable'
import { useFunnelStepsTableModel } from './useFunnelStepsTableModel'

export function FunnelStepsTable(): JSX.Element | null {
    const { insightProps, insightLoading, editingDisabledReason } = useValues(insightLogic)
    const { breakdownFilter } = useValues(insightVizDataLogic(insightProps))
    const { steps, querySource, flattenedBreakdowns, getFunnelsColor, isStepOptional } = useValues(
        funnelDataLogic(insightProps)
    )
    const { toggleLegendBreakdownVisibility } = useActions(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForSeries } = useActions(funnelPersonsModalLogic(insightProps))
    const { openModal } = useActions(resultCustomizationsModalLogic(insightProps))
    const { isOnlySeries, allChecked, someChecked, toggleAll, isChecked, breakdownLabel, sorting, setSorting } =
        useFunnelStepsTableModel()

    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const quillSurface = useQuillSurface()

    if (quillSurface) {
        return <QuillFunnelStepsTable />
    }

    /** :HACKY: We don't want to allow changing of colors in experiments (they can't be
    saved there). Therefore we use the `disable_baseline` prop on the cached insight passed
    in by experiments as a measure of detecting whether we are in an experiment context.
    Likely this can be done in a better way once experiments are re-written to use their own
    queries. */
    const showCustomizationIcon = !insightProps.cachedInsight?.disable_baseline

    const columnsGrouped = [
        {
            children: [
                {
                    title: isOnlySeries ? (
                        'Breakdown'
                    ) : (
                        <span className="inline-flex items-center gap-2">
                            <LemonCheckbox
                                checked={allChecked ? true : someChecked ? 'indeterminate' : false}
                                onChange={toggleAll}
                                size="small"
                                aria-label="Toggle all breakdowns"
                                disabledReason={editingDisabledReason}
                            />
                            <span className="font-bold">Breakdown</span>
                        </span>
                    ),
                    dataIndex: 'breakdown_value',
                    sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) => {
                        // Unwrap breakdown values to compare them properly
                        const valueA = a.breakdown_value?.length == 1 ? a.breakdown_value[0] : a.breakdown_value
                        const valueB = b.breakdown_value?.length == 1 ? b.breakdown_value[0] : b.breakdown_value

                        // For numeric values, use numeric comparison
                        if (typeof valueA === 'number' && typeof valueB === 'number') {
                            return valueA - valueB
                        }

                        // For string values, use string comparison
                        const labelA = formatBreakdownLabel(
                            valueA,
                            breakdownFilter,
                            allCohorts.results,
                            formatPropertyValueForDisplay
                        )
                        const labelB = formatBreakdownLabel(
                            valueB,
                            breakdownFilter,
                            allCohorts.results,
                            formatPropertyValueForDisplay
                        )
                        return compareFn()(labelA, labelB)
                    },
                    render: function RenderBreakdownValue(
                        _: void,
                        breakdown: FlattenedFunnelStepByBreakdown
                    ): JSX.Element {
                        const color = getFunnelsColor(breakdown)

                        const label = (
                            <div className="flex justify-between items-center">
                                <span className="inline-flex items-center gap-2">
                                    {breakdownLabel(breakdown)}
                                    {breakdown.compare_label && (
                                        <LemonTag>{capitalizeFirstLetter(breakdown.compare_label)}</LemonTag>
                                    )}
                                </span>
                                {showCustomizationIcon && (
                                    <LemonColorButton
                                        onClick={() => openModal(breakdown)}
                                        color={color}
                                        type="tertiary"
                                        size="small"
                                        disabledReason={editingDisabledReason}
                                    />
                                )}
                            </div>
                        )
                        return isOnlySeries ? (
                            <span className="font-medium">{label}</span>
                        ) : (
                            <LemonCheckbox
                                checked={isChecked(breakdown)}
                                onChange={() =>
                                    toggleLegendBreakdownVisibility(getVisibilityKey(breakdown.breakdown_value))
                                }
                                label={label}
                                disabledReason={editingDisabledReason}
                            />
                        )
                    },
                },
                {
                    title: (
                        <>
                            Total
                            <br />
                            conversion
                        </>
                    ),
                    key: 'total_conversion',
                    render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                        percentage(breakdown?.conversionRates?.total ?? 0, 2, true),
                    align: 'right',
                    sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                        (a?.conversionRates?.total ?? 0) - (b?.conversionRates?.total ?? 0),
                },
            ],
        },
        ...steps.map((step, stepIndex) => ({
            title: (
                <LemonRow
                    icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />}
                    style={{ font: 'inherit', padding: 0 }}
                    size="small"
                >
                    <EntityFilterInfo
                        filter={getFunnelStepEntity(querySource, stepIndex, step)}
                        isOptional={isStepOptional(stepIndex + 1)}
                    />
                </LemonRow>
            ),
            children: [
                {
                    title: stepIndex === 0 ? 'Entered' : 'Converted',
                    key: `step_${stepIndex}_conversion`,
                    render: function RenderCompleted(
                        _: void,
                        breakdown: FlattenedFunnelStepByBreakdown
                    ): JSX.Element | undefined {
                        const stepSeries = breakdown.steps?.[stepIndex]
                        return (
                            stepSeries &&
                            (canOpenPersonModal ? (
                                <ValueInspectorButton
                                    onClick={() =>
                                        openPersonsModalForSeries({ step, series: stepSeries, converted: true })
                                    }
                                >
                                    {humanFriendlyNumber(stepSeries.count ?? 0)}
                                </ValueInspectorButton>
                            ) : (
                                <>{humanFriendlyNumber(stepSeries.count ?? 0)}</>
                            ))
                        )
                    },
                    align: 'right',
                    sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                        (a.steps?.[stepIndex]?.count ?? 0) - (b.steps?.[stepIndex]?.count ?? 0),
                },
                ...(stepIndex === 0
                    ? []
                    : [
                          {
                              title: 'Dropped off',
                              key: `step_${stepIndex}_dropoff`,
                              render: function RenderDropped(
                                  _: void,
                                  breakdown: FlattenedFunnelStepByBreakdown
                              ): JSX.Element | undefined {
                                  const stepSeries = breakdown.steps?.[stepIndex]
                                  return (
                                      stepSeries &&
                                      (canOpenPersonModal ? (
                                          <ValueInspectorButton
                                              onClick={() =>
                                                  openPersonsModalForSeries({
                                                      step,
                                                      series: stepSeries,
                                                      converted: false,
                                                  })
                                              }
                                          >
                                              {humanFriendlyNumber(stepSeries.droppedOffFromPrevious ?? 0)}
                                          </ValueInspectorButton>
                                      ) : (
                                          <>{humanFriendlyNumber(stepSeries.droppedOffFromPrevious ?? 0)}</>
                                      ))
                                  )
                              },
                              align: 'right',
                              sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                                  (a.steps?.[stepIndex]?.droppedOffFromPrevious ?? 0) -
                                  (b.steps?.[stepIndex]?.droppedOffFromPrevious ?? 0),
                          },
                      ]),
                {
                    title: (
                        <>
                            Conversion
                            <br />
                            so&nbsp;far
                        </>
                    ),
                    key: `step_${stepIndex}_conversion_so_far`,
                    render: function RenderConversionSoFar(
                        _: void,
                        breakdown: FlattenedFunnelStepByBreakdown
                    ): JSX.Element | string {
                        const significance = getSignificanceFromBreakdownStep(breakdown, step.order)
                        return significance?.total ? (
                            <LemonRow
                                className="funnel-significance-highlight"
                                tooltip="Significantly different from other breakdown values"
                                icon={<IconFlag />}
                                size="small"
                            >
                                {percentage(breakdown.steps?.[step.order]?.conversionRates.total ?? 0, 2, true)}
                            </LemonRow>
                        ) : (
                            percentage(breakdown.steps?.[step.order]?.conversionRates.total ?? 0, 2, true)
                        )
                    },
                    align: 'right',
                    sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                        (a.steps?.[step.order]?.conversionRates.total ?? 0) -
                        (b.steps?.[step.order]?.conversionRates.total ?? 0),
                },
                ...(stepIndex === 0
                    ? []
                    : [
                          {
                              title: (
                                  <>
                                      Conversion
                                      <br />
                                      from&nbsp;previous
                                  </>
                              ),
                              key: `step_${stepIndex}_conversion_from_prev`,
                              render: function RenderConversionFromPrevious(
                                  _: void,
                                  breakdown: FlattenedFunnelStepByBreakdown
                              ): JSX.Element | string {
                                  const significance = getSignificanceFromBreakdownStep(breakdown, step.order)
                                  // Only flag as significant here if not flagged already in "Conversion so far"
                                  return !significance?.total && significance?.fromPrevious ? (
                                      <LemonRow
                                          className="funnel-significance-highlight"
                                          tooltip="Significantly different from other breakdown values"
                                          icon={<IconFlag />}
                                          size="small"
                                      >
                                          {percentage(
                                              breakdown.steps?.[step.order]?.conversionRates.fromPrevious ?? 0,
                                              2,
                                              true
                                          )}
                                      </LemonRow>
                                  ) : (
                                      percentage(
                                          breakdown.steps?.[step.order]?.conversionRates.fromPrevious ?? 0,
                                          2,
                                          true
                                      )
                                  )
                              },
                              align: 'right',
                              sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                                  (a.steps?.[step.order]?.conversionRates.fromPrevious ?? 0) -
                                  (b.steps?.[step.order]?.conversionRates.fromPrevious ?? 0),
                          },
                          {
                              title: (
                                  <>
                                      Median
                                      <br />
                                      time
                                  </>
                              ),
                              key: `step_${stepIndex}_median_time`,
                              render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                                  breakdown.steps?.[step.order]?.median_conversion_time != undefined
                                      ? humanFriendlyDuration(breakdown.steps[step.order].median_conversion_time, {
                                            maxUnits: 3,
                                        })
                                      : '–',
                              align: 'right',
                              width: 0,
                              className: 'whitespace-nowrap',
                              sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                                  (a.steps?.[step.order]?.median_conversion_time ?? 0) -
                                  (b.steps?.[step.order]?.median_conversion_time ?? 0),
                          },
                          {
                              title: (
                                  <>
                                      Average
                                      <br />
                                      time
                                  </>
                              ),
                              key: `step_${stepIndex}_average_time`,
                              render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                                  breakdown.steps?.[step.order]?.average_conversion_time != undefined
                                      ? humanFriendlyDuration(breakdown.steps[step.order].average_conversion_time, {
                                            maxUnits: 3,
                                        })
                                      : '–',
                              align: 'right',
                              width: 0,
                              className: 'whitespace-nowrap',
                              sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                                  (a.steps?.[step.order]?.average_conversion_time ?? 0) -
                                  (b.steps?.[step.order]?.average_conversion_time ?? 0),
                          },
                      ]),
            ] as LemonTableColumn<FlattenedFunnelStepByBreakdown, keyof FlattenedFunnelStepByBreakdown>[],
        })),
    ] as LemonTableColumnGroup<FlattenedFunnelStepByBreakdown>[]

    return (
        <LemonTable
            dataSource={flattenedBreakdowns}
            columns={columnsGrouped}
            loading={insightLoading}
            rowKey="breakdownIndex"
            data-attr="funnel-breakdown-table"
            rowStatus={(record) => (record.significant ? 'highlighted' : null)}
            rowRibbonColor={getFunnelsColor}
            firstColumnSticky
            sorting={sorting}
            useURLForSorting={false}
            onSort={setSorting}
        />
    )
}
