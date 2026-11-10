// Invented shop data exercises SQL column mapping, mixed units, missing values, and formatted month labels.
const rows = [
    ['Feb 2026', 2400, 300, null, 34],
    ['Mar 2026', 2800, 450, 0.2, 41],
    ['Apr 2026', 3200, 350, 0.09, 45],
    ['May 2026', 3000, 500, -0.01, 43],
    ['Jun 2026', 3700, 400, 0.17, 49],
    ['Jul 2026 (est.)', 3900, 650, 0.11, 53],
]

const source = { kind: 'HogQLQuery', query: 'SELECT month, sales, renewals, growth, orders FROM example_shop_monthly' }
const xAxis = { column: 'month' }
const sales = {
    column: 'sales',
    settings: {
        display: { label: 'Sales', color: '#1d4aff', displayType: 'bar' },
        formatting: { style: 'number', prefix: '$', decimalPlaces: 0 },
    },
}
const renewals = {
    column: 'renewals',
    settings: {
        display: { label: 'Renewals', color: '#8fa6ff', displayType: 'bar' },
        formatting: { style: 'number', prefix: '$', decimalPlaces: 0 },
    },
}
const growth = {
    column: 'growth',
    settings: {
        display: { label: 'Growth', color: '#c77b00', displayType: 'line', yAxisPosition: 'right' },
        formatting: { style: 'percent', decimalPlaces: 1 },
    },
}
const sqlData = { columns: ['month', 'sales', 'renewals', 'growth', 'orders'], rows }

export const DEMO_SQL_INSIGHTS = [
    {
        id: 9120,
        shortId: 'demo-sql-revenue',
        name: 'Shop revenue and growth',
        description: 'Monthly sales and renewals, with growth on the right axis. Invented demo data.',
        query: {
            kind: 'DataVisualizationNode',
            source,
            display: 'ActionsStackedBar',
            chartSettings: {
                xAxis,
                yAxis: [sales, renewals, growth],
                leftYAxisSettings: { startAtZero: true },
                rightYAxisSettings: { startAtZero: false },
            },
        },
        sqlData,
    },
    {
        id: 9121,
        shortId: 'demo-sql-orders',
        name: 'Orders and growth',
        description: 'Monthly orders with growth on a separate scale.',
        query: {
            kind: 'DataVisualizationNode',
            source,
            display: 'ActionsBar',
            chartSettings: {
                xAxis,
                yAxis: [
                    {
                        column: 'orders',
                        settings: {
                            display: { label: 'Orders', color: '#1d4aff', displayType: 'bar' },
                            formatting: { style: 'number', decimalPlaces: 0 },
                        },
                    },
                    growth,
                ],
            },
        },
        sqlData,
    },
    {
        id: 9122,
        shortId: 'demo-sql-lines',
        name: 'Sales and renewals',
        description: 'Two SQL series with saved month labels.',
        query: {
            kind: 'DataVisualizationNode',
            source,
            display: 'ActionsLineGraph',
            chartSettings: {
                xAxis,
                yAxis: [sales, renewals].map((y) => ({
                    ...y,
                    settings: { ...y.settings, display: { ...y.settings.display, displayType: 'line' } },
                })),
            },
        },
        sqlData,
    },
    {
        id: 9123,
        shortId: 'demo-sql-metric',
        name: 'Latest orders',
        description: 'A SQL metric visualization that opens on the web.',
        query: {
            kind: 'DataVisualizationNode',
            source,
            display: 'Metric',
            chartSettings: { xAxis, yAxis: [{ column: 'orders' }], metric: { summary: 'latest' } },
        },
        sqlData,
    },
]
