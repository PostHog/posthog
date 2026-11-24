import type { NotebookComponentProps } from 'lib/components/MarkdownNotebook/types'
import type { NotebookVariable } from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppLayoutApi } from '../generated/api.schemas'

export const appBuilderDemoVariables: NotebookVariable[] = [
    { name: 'region', type: 'string', value: 'All regions' },
    { name: 'weeks', type: 'number', value: 6 },
    { name: 'include_trials', type: 'boolean', value: true },
    { name: 'week', type: 'date', value: '2026-07-27' },
]

export const appBuilderDemoCells: (NotebookComponentProps & { nodeId: string; returnVariable: string })[] = [
    {
        nodeId: 'weekly-signups',
        title: 'Signups and activation',
        code: `SELECT week, signups, toInt(round(signups * activation_rate)) AS activated
FROM (
    SELECT addDays(toDate('2026-10-12'), (toInt(number) - 11) * 7) AS week,
        toInt(round((120 + number * 15)
            * if({region} = 'Europe', 0.4, if({region} = 'North America', 0.6, 1))
            * if({include_trials}, 1, 0.8))) AS signups,
        if({region} = 'Europe', 0.65, if({region} = 'North America', 0.86, 0.78)) AS activation_rate
    FROM numbers(12)
    WHERE number >= 12 - {weeks}
      AND (empty({week}) OR week >= toDateOrNull({week}))
)
ORDER BY week`,
        returnVariable: 'weekly_growth',
        outputTab: 'visualization',
        vizQuery: {
            kind: 'DataVisualizationNode',
            display: 'ActionsLineGraph',
            chartSettings: { xAxis: { column: 'week' }, yAxis: [{ column: 'signups' }, { column: 'activated' }] },
        },
    },
    {
        nodeId: 'total-signups',
        title: 'Signups in selected period',
        code: 'SELECT sum(signups) AS signups FROM weekly_growth',
        returnVariable: 'signup_total',
        outputTab: 'visualization',
        height: 220,
        vizQuery: { kind: 'DataVisualizationNode', display: 'BoldNumber' },
    },
    {
        nodeId: 'activation-rate',
        title: 'Activation rate in selected period',
        code: 'SELECT round(100.0 * sum(activated) / nullIf(sum(signups), 0), 1) AS activation_rate FROM weekly_growth',
        returnVariable: 'activation_summary',
        outputTab: 'visualization',
        height: 220,
        vizQuery: {
            kind: 'DataVisualizationNode',
            display: 'BoldNumber',
            tableSettings: { columns: [{ column: 'activation_rate', settings: { formatting: { suffix: '%' } } }] },
        },
    },
    {
        nodeId: 'growth-table',
        title: 'Weekly breakdown',
        code: 'SELECT * FROM weekly_growth',
        returnVariable: 'growth_table',
        outputTab: 'results',
    },
]

export function appBuilderDemoResults(
    variables: NotebookVariable[]
): Record<
    string,
    { columns: string[]; types: string[][]; row_count: number; first_page: (string | number | null)[][] }
> {
    const values = Object.fromEntries(variables.map(({ name, value }) => [name, value]))
    const regionScale = values.region === 'Europe' ? 0.4 : values.region === 'North America' ? 0.6 : 1
    const rate = values.region === 'Europe' ? 0.65 : values.region === 'North America' ? 0.86 : 0.78
    const rows = Array.from({ length: 12 }, (_, index) => {
        const date = new Date('2026-10-12T00:00:00Z')
        date.setUTCDate(date.getUTCDate() + (index - 11) * 7)
        const signups = Math.round((120 + index * 15) * regionScale * (values.include_trials ? 1 : 0.8))
        const active = signups * rate
        const lower = Math.floor(active)
        const activated = active - lower === 0.5 ? lower + (lower % 2) : Math.round(active)
        return [date.toISOString().slice(0, 10), signups, activated]
    })
        .slice(-Number(values.weeks))
        .filter(([week]) => !values.week || String(week) >= String(values.week).slice(0, 10))
    const signups = rows.reduce((total, row) => total + Number(row[1]), 0)
    const activated = rows.reduce((total, row) => total + Number(row[2]), 0)
    const growth = {
        columns: ['week', 'signups', 'activated'],
        types: [
            ['week', 'Date'],
            ['signups', 'UInt64'],
            ['activated', 'UInt64'],
        ],
        row_count: rows.length,
        first_page: rows,
    }
    return {
        'weekly-signups': growth,
        'growth-table': growth,
        'total-signups': {
            columns: ['signups'],
            types: [['signups', 'UInt64']],
            row_count: 1,
            first_page: [[signups]],
        },
        'activation-rate': {
            columns: ['activation_rate'],
            types: [['activation_rate', 'Float64']],
            row_count: 1,
            first_page: [[signups ? Math.round((1000 * activated) / signups) / 10 : null]],
        },
    }
}

export const appBuilderDemoLayout: NotebookAppLayoutApi = {
    title: 'Product weekly review',
    description: 'Explore synthetic signup and activation data by region and week.',
    full_width: true,
    tabs: [
        { id: 'overview', title: 'Overview' },
        { id: 'details', title: 'Data and methodology' },
    ],
    blocks: [
        {
            id: 'region',
            kind: 'input',
            tab_id: 'overview',
            width: 3,
            variable: 'region',
            title: 'Region',
            input_kind: 'select',
            options: ['All regions', 'North America', 'Europe'],
        },
        {
            id: 'window',
            kind: 'input',
            tab_id: 'overview',
            width: 3,
            variable: 'weeks',
            title: 'Lookback (weeks)',
            input_kind: 'slider',
            min: 1,
            max: 12,
            step: 1,
        },
        {
            id: 'include',
            kind: 'input',
            tab_id: 'overview',
            width: 3,
            variable: 'include_trials',
            title: 'Include trial accounts',
            input_kind: 'auto',
        },
        {
            id: 'first-week',
            kind: 'input',
            tab_id: 'overview',
            width: 3,
            variable: 'week',
            title: 'Starting week',
            input_kind: 'auto',
        },
        {
            id: 'signups',
            kind: 'cell',
            tab_id: 'overview',
            width: 6,
            node_id: 'total-signups',
            title: 'Signups in selected period',
            display: 'output',
        },
        {
            id: 'activation',
            kind: 'cell',
            tab_id: 'overview',
            width: 6,
            node_id: 'activation-rate',
            title: 'Activation rate in selected period',
            display: 'output',
        },
        {
            id: 'trend',
            kind: 'cell',
            tab_id: 'overview',
            width: 12,
            node_id: 'weekly-signups',
            title: 'Acquisition and activation',
            display: 'output',
        },
        {
            id: 'table',
            kind: 'cell',
            tab_id: 'details',
            width: 12,
            node_id: 'growth-table',
            title: 'Weekly breakdown',
            display: 'both',
        },
        {
            id: 'methodology',
            kind: 'text',
            tab_id: 'details',
            width: 12,
            text: '## Methodology\n\nThis demo uses invented weekly signup counts. Region, lookback, and trial inclusion feed the source query. The metric cards calculate total signups and activation rate from those same rows.\n\nActivation means completing the first project setup. Weeks start on Monday.',
        },
    ],
}
