import { useActions, useValues } from 'kea'

import { Badge, Button, Checkbox, TableCell, TableHead, TableRow } from '@posthog/quill'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { percentage } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { resultCustomizationsModalLogic } from '~/queries/nodes/InsightViz/resultCustomizationsModalLogic'

import { QuillBreakdownValue } from 'products/product_analytics/frontend/insights/shared/InsightsTable/columns/QuillBreakdownValue'
import { QuillDetailedResultsTable } from 'products/product_analytics/frontend/insights/shared/QuillDetailedResultsTable'
import { QuillSeriesSwatch } from 'products/product_analytics/frontend/insights/shared/QuillSeriesSwatch'

import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { getVisibilityKey } from '../funnelUtils'
import { getFunnelStepEntity } from '../shared/funnelStepSeries'
import { funnelStepColumns } from './funnelStepsTableColumns'
import { QuillFunnelStepMetricCell } from './QuillFunnelStepMetricCell'
import { QuillFunnelStepsTableHead } from './QuillFunnelStepsTableHead'
import { useFunnelStepsTableModel } from './useFunnelStepsTableModel'

const GROUP_START = 'border-l'

export function QuillFunnelStepsTable(): JSX.Element {
    const { insightProps, insightLoading, editingDisabledReason } = useValues(insightLogic)
    const { breakdownFilter } = useValues(insightVizDataLogic(insightProps))
    const { steps, querySource, flattenedBreakdowns, getFunnelsColor, isStepOptional, disableFunnelBreakdownBaseline } =
        useValues(funnelDataLogic(insightProps))
    const { toggleLegendBreakdownVisibility } = useActions(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForSeries } = useActions(funnelPersonsModalLogic(insightProps))
    const { openModal } = useActions(resultCustomizationsModalLogic(insightProps))
    const { isOnlySeries, allChecked, someChecked, toggleAll, isChecked, breakdownLabel, sorting, setSorting } =
        useFunnelStepsTableModel()

    return (
        <QuillDetailedResultsTable
            data-attr="funnel-breakdown-table"
            loading={insightLoading}
            header={
                <>
                    <TableRow>
                        <TableHead sticky="left" />
                        <TableHead />
                        {steps.map((step, stepIndex) => (
                            <TableHead
                                key={stepIndex}
                                colSpan={funnelStepColumns(stepIndex).length}
                                className={GROUP_START}
                            >
                                {/* Zero width with a full minimum width keeps a long step name from widening its columns, so the name is cut off. */}
                                <span className="flex w-0 min-w-full items-center gap-2 text-xs normal-case tracking-normal text-foreground">
                                    <Badge className="shrink-0">{stepIndex + 1}</Badge>
                                    <EntityFilterInfo
                                        filter={getFunnelStepEntity(querySource, stepIndex, step)}
                                        isOptional={isStepOptional(stepIndex + 1)}
                                    />
                                </span>
                            </TableHead>
                        ))}
                    </TableRow>
                    <TableRow>
                        <QuillFunnelStepsTableHead
                            columnKey="breakdown_value"
                            title="Breakdown"
                            sorting={sorting}
                            onSort={setSorting}
                            sticky="left"
                            before={
                                !isOnlySeries && (
                                    // The checkbox renders inside a tooltip wrapper, so this span is what lines it up with the label.
                                    <span className="mr-3 inline-flex align-middle">
                                        <Checkbox
                                            aria-label="Toggle all breakdowns"
                                            checked={allChecked}
                                            indeterminate={someChecked && !allChecked}
                                            onCheckedChange={toggleAll}
                                            disabledReason={editingDisabledReason}
                                        />
                                    </span>
                                )
                            }
                        />
                        <QuillFunnelStepsTableHead
                            columnKey="total_conversion"
                            title="Total conversion"
                            sorting={sorting}
                            onSort={setSorting}
                            align="right"
                        />
                        {steps.map((_, stepIndex) =>
                            funnelStepColumns(stepIndex).map((column, columnIndex) => (
                                <QuillFunnelStepsTableHead
                                    key={column.key}
                                    columnKey={column.key}
                                    title={column.title}
                                    sorting={sorting}
                                    onSort={setSorting}
                                    align="right"
                                    className={columnIndex === 0 ? GROUP_START : undefined}
                                />
                            ))
                        )}
                    </TableRow>
                </>
            }
        >
            {flattenedBreakdowns.map((breakdown) => {
                const label = breakdownLabel(breakdown)
                const swatch = <QuillSeriesSwatch color={getFunnelsColor(breakdown)} />

                return (
                    <TableRow
                        key={breakdown.breakdownIndex}
                        // Quill's selected row is its highlighted row, which is what a significant breakdown gets.
                        data-state={breakdown.significant ? 'selected' : undefined}
                        className={breakdown.significant ? 'font-semibold' : undefined}
                    >
                        <TableCell sticky="left">
                            <span className="flex min-w-0 items-center gap-1">
                                {!isOnlySeries && (
                                    <Checkbox
                                        aria-label={`Show ${label || 'breakdown'}`}
                                        checked={isChecked(breakdown)}
                                        onCheckedChange={() =>
                                            toggleLegendBreakdownVisibility(getVisibilityKey(breakdown.breakdown_value))
                                        }
                                        disabledReason={editingDisabledReason}
                                        className="mr-2"
                                    />
                                )}
                                <QuillBreakdownValue
                                    label={label}
                                    breakdownFilter={breakdownFilter}
                                    compareValue={
                                        breakdown.compare_label && capitalizeFirstLetter(breakdown.compare_label)
                                    }
                                    swatch={
                                        // :HACKY: Experiments can't save colors, and mark their funnels with `disable_baseline`.
                                        disableFunnelBreakdownBaseline ? (
                                            swatch
                                        ) : (
                                            <Button
                                                size="icon-xs"
                                                aria-label="Change color"
                                                tooltip="Change color"
                                                disabledReason={editingDisabledReason}
                                                onClick={() => openModal(breakdown)}
                                            >
                                                {swatch}
                                            </Button>
                                        )
                                    }
                                />
                            </span>
                        </TableCell>
                        <TableCell align="right" className="tabular-nums">
                            {percentage(breakdown.conversionRates?.total ?? 0, 2, true)}
                        </TableCell>
                        {steps.map((step, stepIndex) =>
                            funnelStepColumns(stepIndex).map((column, columnIndex) => (
                                <QuillFunnelStepMetricCell
                                    key={column.key}
                                    metric={column.metric}
                                    stepOrder={step.order}
                                    breakdown={breakdown}
                                    onOpenPersons={
                                        canOpenPersonModal
                                            ? (series, converted) =>
                                                  openPersonsModalForSeries({ step, series, converted })
                                            : undefined
                                    }
                                    className={columnIndex === 0 ? GROUP_START : undefined}
                                />
                            ))
                        )}
                    </TableRow>
                )
            })}
        </QuillDetailedResultsTable>
    )
}
