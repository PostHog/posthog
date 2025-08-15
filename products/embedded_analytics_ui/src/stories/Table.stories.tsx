import type { Meta, StoryObj } from '@storybook/react'
import { Table } from '../components/Table'
import { TableColumn, TableResponse, TableRow } from '../types/schemas'

const meta: Meta<typeof Table> = {
    title: 'Analytics/Table',
    component: Table,
    parameters: {
        layout: 'padded',
        docs: {
            description: {
                component: 'Display tabular data with sorting, pagination, and optional fill bars.',
            },
        },
    },
    argTypes: {
        onRowClick: { action: 'row clicked' },
        onSort: { action: 'sort changed' },
        onPageChange: { action: 'page changed' },
        onPageSizeChange: { action: 'page size changed' },
    },
}

export default meta
type Story = StoryObj<typeof Table>

// Sample table columns
const standardColumns: TableColumn[] = [
    {
        key: 'breakdown_value',
        label: 'Page',
        type: 'string' as const,
        sortable: true,
    },
    {
        key: 'visitors',
        label: 'Visitors',
        type: 'number' as const,
        sortable: true,
    },
    {
        key: 'pageviews',
        label: 'Page Views',
        type: 'number' as const,
        sortable: true,
    },
    {
        key: 'bounce_rate',
        label: 'Bounce Rate',
        type: 'percentage' as const,
        sortable: true,
    },
]

const browserColumns: TableColumn[] = [
    {
        key: 'breakdown_value',
        label: 'Browser',
        type: 'string' as const,
        sortable: true,
    },
    {
        key: 'visitors',
        label: 'Visitors',
        type: 'number' as const,
        sortable: true,
    },
    {
        key: 'market_share',
        label: 'Market Share',
        type: 'percentage' as const,
        sortable: true,
    },
    {
        key: 'avg_session_duration',
        label: 'Avg Session',
        type: 'number' as const,
        sortable: false,
    },
]

// Sample table rows
const generatePageData = (): TableRow[] => [
    {
        breakdown_value: '/home',
        visitors: 5420,
        pageviews: 8230,
        bounce_rate: 23.4,
        fillRatio: 1.0,
    },
    {
        breakdown_value: '/about',
        visitors: 3210,
        pageviews: 4560,
        bounce_rate: 31.2,
        fillRatio: 0.59,
    },
    {
        breakdown_value: '/products',
        visitors: 2840,
        pageviews: 5120,
        bounce_rate: 28.7,
        fillRatio: 0.52,
    },
    {
        breakdown_value: '/contact',
        visitors: 1680,
        pageviews: 2340,
        bounce_rate: 45.1,
        fillRatio: 0.31,
    },
    {
        breakdown_value: '/blog',
        visitors: 980,
        pageviews: 1450,
        bounce_rate: 38.9,
        fillRatio: 0.18,
    },
    {
        breakdown_value: '/pricing',
        visitors: 750,
        pageviews: 1120,
        bounce_rate: 42.3,
        fillRatio: 0.14,
    },
    {
        breakdown_value: '/support',
        visitors: 420,
        pageviews: 650,
        bounce_rate: 35.7,
        fillRatio: 0.08,
    },
]

const generateBrowserData = (): TableRow[] => [
    {
        breakdown_value: 'Chrome',
        visitors: 12840,
        market_share: 68.5,
        avg_session_duration: 245,
        fillRatio: 1.0,
    },
    {
        breakdown_value: 'Safari',
        visitors: 3420,
        market_share: 18.2,
        avg_session_duration: 198,
        fillRatio: 0.27,
    },
    {
        breakdown_value: 'Firefox',
        visitors: 1680,
        market_share: 8.9,
        avg_session_duration: 267,
        fillRatio: 0.13,
    },
    {
        breakdown_value: 'Edge',
        visitors: 580,
        market_share: 3.1,
        avg_session_duration: 156,
        fillRatio: 0.05,
    },
    {
        breakdown_value: 'Opera',
        visitors: 245,
        market_share: 1.3,
        avg_session_duration: 189,
        fillRatio: 0.02,
    },
]

const standardTableData: TableResponse = {
    columns: standardColumns,
    rows: generatePageData(),
    count: 127,
    next: 'next-page-token',
    previous: null,
}

const browserTableData: TableResponse = {
    columns: browserColumns,
    rows: generateBrowserData(),
    count: 25,
    next: null,
    previous: 'prev-page-token',
}

export const Default: Story = {
    args: {
        data: standardTableData,
        loading: false,
        currentPage: 1,
        pageSize: 25,
    },
}

export const Loading: Story = {
    args: {
        loading: true,
    },
}

export const WithError: Story = {
    args: {
        error: {
            error: 'Failed to load table data',
            details: 'Database connection timeout. Please try again.',
        },
    },
}

export const WithSorting: Story = {
    args: {
        data: standardTableData,
        loading: false,
        currentSort: { column: 'visitors', direction: 'desc' },
        currentPage: 1,
        pageSize: 25,
    },
}

export const BrowserData: Story = {
    args: {
        data: browserTableData,
        loading: false,
        currentPage: 2,
        pageSize: 10,
    },
    parameters: {
        docs: {
            description: {
                story: 'Example showing browser analytics data with different column types.',
            },
        },
    },
}

export const WithoutFillBars: Story = {
    args: {
        data: {
            ...standardTableData,
            rows: standardTableData.rows.map(({ fillRatio: _, ...rowWithoutFill }) => rowWithoutFill),
        },
        loading: false,
        currentPage: 1,
        pageSize: 25,
    },
}

export const WithClickHandlers: Story = {
    args: {
        data: standardTableData,
        loading: false,
        currentPage: 1,
        pageSize: 25,
        onRowClick: (row): void => {
            alert(`Clicked on ${row.breakdown_value}`)
        },
    },
    parameters: {
        docs: {
            description: {
                story: 'Click on any table row to see the click handler in action.',
            },
        },
    },
}

export const SmallPageSize: Story = {
    args: {
        data: standardTableData,
        loading: false,
        currentPage: 1,
        pageSize: 3,
    },
}

export const EmptyTable: Story = {
    args: {
        data: {
            columns: standardColumns,
            rows: [],
            count: 0,
            next: null,
            previous: null,
        },
        loading: false,
        currentPage: 1,
        pageSize: 25,
    },
}

export const SingleRow: Story = {
    args: {
        data: {
            columns: standardColumns,
            rows: [generatePageData()[0]],
            count: 1,
            next: null,
            previous: null,
        },
        loading: false,
        currentPage: 1,
        pageSize: 25,
    },
}

export const LargeNumbers: Story = {
    args: {
        data: {
            columns: [
                {
                    key: 'breakdown_value',
                    label: 'Campaign',
                    type: 'string' as const,
                    sortable: true,
                },
                {
                    key: 'impressions',
                    label: 'Impressions',
                    type: 'number' as const,
                    sortable: true,
                },
                {
                    key: 'clicks',
                    label: 'Clicks',
                    type: 'number' as const,
                    sortable: true,
                },
                {
                    key: 'ctr',
                    label: 'CTR',
                    type: 'percentage' as const,
                    sortable: true,
                },
            ],
            rows: [
                {
                    breakdown_value: 'Summer Sale 2024',
                    impressions: 2847593,
                    clicks: 45821,
                    ctr: 1.61,
                    fillRatio: 1.0,
                },
                {
                    breakdown_value: 'Holiday Special',
                    impressions: 1234567,
                    clicks: 28934,
                    ctr: 2.34,
                    fillRatio: 0.43,
                },
                {
                    breakdown_value: 'New Product Launch',
                    impressions: 987654,
                    clicks: 19876,
                    ctr: 2.01,
                    fillRatio: 0.35,
                },
            ],
            count: 15,
            next: 'next-token',
            previous: null,
        },
        loading: false,
        currentPage: 1,
        pageSize: 25,
    },
}

export const MixedDataTypes: Story = {
    args: {
        data: {
            columns: [
                {
                    key: 'breakdown_value',
                    label: 'Source',
                    type: 'string' as const,
                    sortable: true,
                },
                {
                    key: 'users',
                    label: 'Users',
                    type: 'number' as const,
                    sortable: true,
                },
                {
                    key: 'conversion_rate',
                    label: 'Conversion',
                    type: 'percentage' as const,
                    sortable: true,
                },
                {
                    key: 'revenue',
                    label: 'Revenue',
                    type: 'number' as const,
                    sortable: true,
                },
                {
                    key: 'status',
                    label: 'Status',
                    type: 'string' as const,
                    sortable: false,
                },
            ],
            rows: [
                {
                    breakdown_value: 'Google Ads',
                    users: 5420,
                    conversion_rate: 3.45,
                    revenue: 15234.5,
                    status: 'Active',
                    fillRatio: 1.0,
                },
                {
                    breakdown_value: 'Facebook',
                    users: 3210,
                    conversion_rate: 2.87,
                    revenue: 8976.25,
                    status: 'Active',
                    fillRatio: 0.59,
                },
                {
                    breakdown_value: 'Twitter',
                    users: 1680,
                    conversion_rate: 1.94,
                    revenue: 4532.1,
                    status: 'Paused',
                    fillRatio: 0.31,
                },
            ],
            count: 8,
            next: null,
            previous: null,
        },
        loading: false,
        currentPage: 1,
        pageSize: 25,
    },
}
