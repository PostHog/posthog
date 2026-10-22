import './RetentionHeatmap.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { Heatmap, type HeatmapCellDatum, type HeatmapCellStyle } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { insightLogic } from 'scenes/insights/insightLogic'

import { retentionLogic, OVERALL_MEAN_KEY } from '../retentionLogic'
import { retentionModalLogic } from '../retentionModalLogic'
import { NO_BREAKDOWN_VALUE } from '../types'
import { retentionHeatmapLogic } from './retentionHeatmapLogic'

const ROW_HEIGHT = 34
const SMALL_ROW_HEIGHT = 26

/** One drawn row: a breakdown's mean, or a cohort inside it. Ordered top to bottom. */
interface HeatmapRow {
    key: string
    label: string
    size: number
    /** Drives the cell color. One entry per interval; a shorter row has no cell past its end. */
    percentages: (number | undefined)[]
    /** Shown instead of the percentage when the aggregation is over a property value. */
    aggregationValues: (number | undefined)[]
    inProgress: boolean[]
    isMean: boolean
    breakdownValue: string
    /** Index inside the breakdown group, which is what the person modal takes. */
    cohortIndex: number
    indented: boolean
}

export function RetentionHeatmap({
    inSharedMode = false,
    embedded = false,
}: {
    inSharedMode?: boolean
    embedded?: boolean
}): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const {
        tableRowsSplitByBreakdownValue,
        hideSizeColumn,
        retentionVizOptions,
        theme,
        expandedBreakdowns,
        retentionMeans,
        breakdownDisplayNames,
        tableHeaders,
        retentionFilter,
        isPropertyValueAggregation,
        hoveredColumn,
    } = useValues(retentionHeatmapLogic(insightProps))
    const { toggleBreakdown, setHoveredColumn } = useActions(retentionHeatmapLogic(insightProps))
    const { updateInsightFilter } = useActions(retentionLogic(insightProps))
    const { openModal } = useActions(retentionModalLogic(insightProps))
    const { canOpenPersonModal } = useValues(retentionModalLogic(insightProps))
    const chartTheme = useChartTheme()

    const selectedInterval = retentionFilter?.selectedInterval ?? null
    const allowSelectingColumns = !inSharedMode && !embedded
    const smallLayout = !!retentionVizOptions?.useSmallLayout
    const rowHeight = smallLayout ? SMALL_ROW_HEIGHT : ROW_HEIGHT
    const cohortColor = theme?.['preset-1'] || '#1d4aff'
    const meanColor = theme?.['preset-2'] || cohortColor

    const rows = useMemo<HeatmapRow[]>(
        () =>
            Object.entries(tableRowsSplitByBreakdownValue).flatMap(([breakdownValue, cohortRows]) => {
                const noBreakdown = breakdownValue === NO_BREAKDOWN_VALUE
                const meanData = retentionMeans[noBreakdown ? OVERALL_MEAN_KEY : breakdownValue]
                const expanded = expandedBreakdowns[breakdownValue]
                const meanRow: HeatmapRow = {
                    key: `mean:${breakdownValue}`,
                    label: noBreakdown ? 'Mean' : breakdownDisplayNames[breakdownValue] || breakdownValue,
                    size: noBreakdown
                        ? cohortRows.length
                            ? Math.round((meanData?.totalCohortSize ?? 0) / cohortRows.length)
                            : 0
                        : (meanData?.totalCohortSize ?? 0),
                    percentages: tableHeaders.map((_, i) => meanData?.meanPercentages?.[i] ?? 0),
                    aggregationValues: tableHeaders.map((_, i) => meanData?.meanValues?.[i] ?? 0),
                    inProgress: tableHeaders.map(() => false),
                    isMean: true,
                    breakdownValue,
                    cohortIndex: -1,
                    indented: false,
                }
                if (!expanded) {
                    return [meanRow]
                }
                return [
                    meanRow,
                    ...cohortRows.map((row, cohortIndex) => ({
                        key: `${breakdownValue}:${cohortIndex}`,
                        label: row.label,
                        size: row.cohortSize,
                        percentages: tableHeaders.map((_, i) => row.values[i]?.percentage),
                        aggregationValues: tableHeaders.map((_, i) => row.values[i]?.aggregation_value ?? 0),
                        inProgress: tableHeaders.map((_, i) => !!row.values[i]?.isCurrentPeriod),
                        isMean: false,
                        breakdownValue,
                        cohortIndex,
                        indented: true,
                    })),
                ]
            }),
        [tableRowsSplitByBreakdownValue, retentionMeans, expandedBreakdowns, breakdownDisplayNames, tableHeaders]
    )

    // The heatmap indexes rows bottom-up, so the drawn grid is this list reversed.
    const rowAt = useCallback((yIndex: number): HeatmapRow | undefined => rows[rows.length - 1 - yIndex], [rows])
    const yLabels = useMemo(() => rows.map((row) => row.label).reverse(), [rows])
    const cells = useMemo(
        () => rows.map((row) => row.percentages.map((percentage) => percentage ?? 0)).reverse(),
        [rows]
    )

    const cellLabel = useCallback(
        (cell: HeatmapCellDatum): string | null => {
            const row = rowAt(cell.yIndex)
            if (!row || row.percentages[cell.xIndex] === undefined) {
                return null
            }
            return isPropertyValueAggregation
                ? humanFriendlyNumber(row.aggregationValues[cell.xIndex] ?? 0)
                : `${(row.percentages[cell.xIndex] ?? 0).toFixed(1)}%`
        },
        [rowAt, isPropertyValueAggregation]
    )

    const cellStyle = useCallback(
        (cell: HeatmapCellDatum): HeatmapCellStyle | null => {
            const row = rowAt(cell.yIndex)
            if (!row || row.percentages[cell.xIndex] === undefined) {
                return null
            }
            if (row.inProgress[cell.xIndex]) {
                return { outlined: true }
            }
            return row.isMean ? { color: meanColor } : null
        },
        [rowAt, meanColor]
    )

    const onCellClick = useCallback(
        (cell: HeatmapCellDatum): void => {
            const row = rowAt(cell.yIndex)
            if (!row || row.isMean || inSharedMode || !canOpenPersonModal) {
                return
            }
            row.breakdownValue === NO_BREAKDOWN_VALUE
                ? openModal(row.cohortIndex, null, cell.xIndex)
                : openModal(row.cohortIndex, row.breakdownValue, cell.xIndex)
        },
        [rowAt, inSharedMode, canOpenPersonModal, openModal]
    )

    const highlightedColumns = useMemo(
        () =>
            [selectedInterval, hoveredColumn].filter(
                (column, index, all): column is number => column !== null && all.indexOf(column) === index
            ),
        [selectedInterval, hoveredColumn]
    )

    const config = useMemo(
        () => ({
            colorScale: 'linear' as const,
            color: cohortColor,
            hideXAxis: true,
            hideYAxis: true,
            margins: { top: 0, right: 0, bottom: 0, left: 0 },
            tooltip: { enabled: false },
            cellLabel,
            cellStyle,
            highlightedColumns,
        }),
        [cohortColor, cellLabel, cellStyle, highlightedColumns]
    )

    if (rows.length === 0 || tableHeaders.length === 0) {
        return null
    }

    return (
        <div
            className={clsx('RetentionHeatmap', { 'RetentionHeatmap--small': smallLayout })}
            data-attr="retention-table"
        >
            <div className="RetentionHeatmap__rows">
                <div className="RetentionHeatmap__head">
                    <span>Cohort</span>
                    {!hideSizeColumn && <span className="RetentionHeatmap__size">Size</span>}
                </div>
                {rows.map((row) => (
                    <button
                        key={row.key}
                        type="button"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: rowHeight }}
                        className={clsx('RetentionHeatmap__row', { 'RetentionHeatmap__row--indented': row.indented })}
                        onClick={() => {
                            if (row.isMean) {
                                toggleBreakdown(row.breakdownValue)
                            } else if (!inSharedMode && canOpenPersonModal) {
                                openModal(
                                    row.cohortIndex,
                                    row.breakdownValue === NO_BREAKDOWN_VALUE ? null : row.breakdownValue
                                )
                            }
                        }}
                    >
                        {row.isMean &&
                            (expandedBreakdowns[row.breakdownValue] ? <IconChevronDown /> : <IconChevronRight />)}
                        <span className="RetentionHeatmap__label">{row.label}</span>
                        {!hideSizeColumn && <span className="RetentionHeatmap__size">{row.size}</span>}
                    </button>
                ))}
            </div>

            <div className="RetentionHeatmap__grid">
                <div
                    className="RetentionHeatmap__head RetentionHeatmap__intervals"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ gridTemplateColumns: `repeat(${tableHeaders.length}, minmax(0, 1fr))` }}
                >
                    {tableHeaders.map((header, columnIndex) => (
                        <button
                            key={header}
                            type="button"
                            disabled={!allowSelectingColumns}
                            className={clsx('RetentionHeatmap__interval', {
                                'RetentionHeatmap__interval--selected': columnIndex === selectedInterval,
                                'RetentionHeatmap__interval--hovered': columnIndex === hoveredColumn,
                            })}
                            onClick={() =>
                                updateInsightFilter({
                                    selectedInterval: columnIndex === selectedInterval ? null : columnIndex,
                                })
                            }
                            onMouseEnter={() => allowSelectingColumns && setHoveredColumn(columnIndex)}
                            onMouseLeave={() => allowSelectingColumns && setHoveredColumn(null)}
                        >
                            {header}
                        </button>
                    ))}
                </div>
                <Tooltip title="Click a cell to see who is in it" placement="top-start" delayMs={1500}>
                    {/* eslint-disable-next-line react/forbid-dom-props */}
                    <div className="RetentionHeatmap__canvas" style={{ height: rows.length * rowHeight }}>
                        <Heatmap
                            xLabels={tableHeaders}
                            yLabels={yLabels}
                            cells={cells}
                            theme={chartTheme}
                            config={config}
                            onCellClick={onCellClick}
                        />
                    </div>
                </Tooltip>
            </div>
        </div>
    )
}
