import { z } from 'zod'

import { ChartDisplayType, ChartSettings, TableSettings } from '@/schema/query'

import { readExpressionProp, removeProp, upsertProp } from './cellTags'

// The SQL chart has no renderer for WorldMap, and TwoDimensionalHeatmap needs heatmap column
// settings this schema does not carry, so either one opens the cell on an empty chart.
const SqlCellDisplayType = ChartDisplayType.exclude(['WorldMap', 'TwoDimensionalHeatmap'])

export const CellVisualizationSchema = z
    .object({
        display: SqlCellDisplayType.describe(
            'Chart type. Use ActionsLineGraph or ActionsAreaGraph for a time series, ActionsBar for categories, ActionsPie for shares of a total, BoldNumber for one headline value, and ActionsTable for a formatted table.'
        ),
        chartSettings: ChartSettings.optional().describe(
            'Axes and chart options. Omit an axis to let the chart pick it: the first date column for X, and every numeric column for Y. Every column named here must be a column the query returns, and a Y column must be numeric.'
        ),
        tableSettings: TableSettings.optional(),
    })
    .strict()

export type CellVisualization = z.infer<typeof CellVisualizationSchema>

export const VISUALIZATION_PARAM_DESCRIPTION =
    'SQL cells only: show the result as a chart instead of the table, like the Visualization tab in the editor. The chart draws from the rows the run returns, so aggregate in SQL to the points you want plotted.'

interface ResultColumns {
    columns?: string[] | null
    types?: unknown[] | null
    row_count?: number | null
    first_page?: unknown[] | null
    has_more?: boolean | null
    previewOnly?: boolean | null
}

// `vizQuery.source` is left out because the node always rebuilds it from the cell's current
// `code`, so a stored copy could only drift from the code.
export function applyVisualization(tagSource: string, visualization: CellVisualization | null): string {
    if (visualization === null) {
        return removeProp(upsertProp(tagSource, 'outputTab', 'results'), 'vizQuery')
    }
    const vizQuery = { kind: 'DataVisualizationNode', ...visualization }
    return upsertProp(upsertProp(tagSource, 'outputTab', 'visualization'), 'vizQuery', vizQuery)
}

function storedVisualization(tagSource: string): CellVisualization | null {
    const vizQuery = readExpressionProp(tagSource, 'vizQuery')
    if (!vizQuery || typeof vizQuery !== 'object') {
        return null
    }
    const parsed = CellVisualizationSchema.safeParse({
        display: (vizQuery as { display?: unknown }).display,
        chartSettings: (vizQuery as { chartSettings?: unknown }).chartSettings,
        tableSettings: (vizQuery as { tableSettings?: unknown }).tableSettings,
    })
    return parsed.success ? parsed.data : null
}

export function storedVisualizationWarnings(tagSource: string): string[] {
    const result = readExpressionProp(tagSource, 'result')
    if (!result || typeof result !== 'object' || !Array.isArray((result as ResultColumns).columns)) {
        return []
    }
    return visualizationWarnings(tagSource, result as ResultColumns)
}

/**
 * Mirrors `toFriendlyClickhouseTypeName` and `isNumericalType` in the frontend
 * dataVisualizationLogic.ts, which decide whether the chart accepts a column as a Y series.
 */
function isNumericClickhouseType(type: string | undefined): boolean {
    if (!type || type.includes('Array') || type.includes('Tuple')) {
        return false
    }
    return type.includes('Int') || type.includes('Float') || type.includes('Decimal')
}

function columnType(result: ResultColumns, column: string): string | undefined {
    const entry = (result.types ?? []).find((type) => Array.isArray(type) && type[0] === column)
    return Array.isArray(entry) && typeof entry[1] === 'string' ? entry[1] : undefined
}

/**
 * Problems that make the chart draw nothing, or less than the agent expects, while the call
 * itself succeeds. The chart drops both axes when one names a missing or non-numeric column, and
 * it plots only the first page of the run, so the agent cannot see either failure otherwise.
 */
export function visualizationWarnings(tagSource: string, result: ResultColumns | null): string[] {
    const visualization = storedVisualization(tagSource)
    if (!visualization || !result?.columns) {
        return []
    }
    const columns = result.columns
    const known = new Set(columns)
    const listed = columns.join(', ')
    const warnings: string[] = []
    const settings = visualization.chartSettings

    const xColumn = settings?.xAxis?.column
    if (xColumn !== undefined && !known.has(xColumn)) {
        warnings.push(`xAxis column '${xColumn}' is not in the result columns: ${listed}.`)
    }
    for (const series of settings?.yAxis ?? []) {
        if (!known.has(series.column)) {
            warnings.push(`yAxis column '${series.column}' is not in the result columns: ${listed}.`)
        } else if (!isNumericClickhouseType(columnType(result, series.column))) {
            warnings.push(
                `yAxis column '${series.column}' is not numeric (${columnType(result, series.column) ?? 'unknown type'}), so the chart cannot plot it.`
            )
        }
    }
    const breakdown = settings?.seriesBreakdownColumn
    if (breakdown && !known.has(breakdown)) {
        warnings.push(`seriesBreakdownColumn '${breakdown}' is not in the result columns: ${listed}.`)
    }
    if (warnings.length > 0) {
        warnings.push('The chart ignores both axes when one of them is invalid. Fix the column names or the query.')
    }

    const plotted = result.first_page?.length ?? 0
    const truncated = !!result.has_more || (result.row_count ?? 0) > plotted
    // A table pages through the rows, and a bold number shows one value, so only a plot loses points.
    // A stored preview keeps fewer rows than the run result the chart restores, so its count proves
    // nothing about the chart. The run that stored it already reported this from the full result.
    if (!['ActionsTable', 'BoldNumber'].includes(visualization.display) && truncated && !result.previewOnly) {
        warnings.push(
            `The chart plots only the first ${plotted} rows of ${result.row_count ?? 'more'}. Aggregate in SQL so the result fits.`
        )
    }
    return warnings
}
