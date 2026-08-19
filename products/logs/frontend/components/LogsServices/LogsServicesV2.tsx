import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSegmentedButton, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'
import type { LemonSegmentedButtonOption, LemonTableColumns } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { logsServicesLogic, SERVICES_PAGE_SIZE, ServiceRow, ServicesViewMode } from './logsServicesLogic'

const DATE_OPTIONS = [
    { value: '-1h', label: 'Last hour' },
    { value: '-24h', label: 'Last 24 hours' },
    { value: '-7d', label: 'Last 7 days' },
    { value: '-30d', label: 'Last 30 days' },
]

const VIEW_MODE_OPTIONS: LemonSegmentedButtonOption<ServicesViewMode>[] = [
    { value: 'list', label: 'List', 'data-attr': 'logs-services-view-mode-list' },
    { value: 'grid', label: 'Grid', 'data-attr': 'logs-services-view-mode-grid' },
]

const COLUMNS: LemonTableColumns<ServiceRow> = [
    { title: 'Service name', dataIndex: 'service_name' },
    {
        title: 'Log volume',
        dataIndex: 'log_count',
        align: 'right',
        render: (_, row) => humanFriendlyNumber(row.log_count),
    },
    {
        title: 'Error rate',
        dataIndex: 'error_rate',
        align: 'right',
        render: (_, row) => {
            const type = row.error_rate > 0.1 ? 'danger' : row.error_rate > 0.01 ? 'warning' : 'success'
            return <LemonTag type={type}>{(row.error_rate * 100).toFixed(1)}%</LemonTag>
        },
    },
]

function ServicesGrid(): JSX.Element {
    return (
        <div className="p-4 text-center text-muted">
            Grid view is not built yet. Switch to List to see your services.
        </div>
    )
}

export function LogsServicesV2(): JSX.Element {
    const { pageRows, services, totalServices, servicesDataLoading, searchTerm, dateFrom, page, viewMode } =
        useValues(logsServicesLogic)
    const { setDateFrom, setSearchTerm, setPage, setViewMode } = useActions(logsServicesLogic)

    return (
        <div className="flex flex-col gap-2 py-2 flex-1 min-h-0">
            {totalServices > services.length && (
                <LemonBanner type="info" className="mb-0">
                    Showing the top {humanFriendlyNumber(services.length)} of {humanFriendlyNumber(totalServices)}{' '}
                    {searchTerm ? 'matching services' : 'services'} by volume.{' '}
                    {searchTerm ? 'Refine your search to see the rest.' : 'Use search to find the rest.'}
                </LemonBanner>
            )}
            <div className="flex items-center justify-between gap-2">
                <LemonSegmentedButton
                    size="small"
                    value={viewMode}
                    onChange={setViewMode}
                    options={VIEW_MODE_OPTIONS}
                />
                <div className="flex items-center gap-2">
                    <LemonInput
                        size="small"
                        type="search"
                        placeholder="Search services"
                        value={searchTerm}
                        onChange={setSearchTerm}
                    />
                    <LemonSelect
                        size="small"
                        value={dateFrom}
                        onChange={(value) => value && setDateFrom(value)}
                        options={DATE_OPTIONS}
                    />
                </div>
            </div>
            {/* The scene container is a fixed height and does not scroll, so this region has to. */}
            <div className="flex-1 min-h-0 overflow-y-auto" data-attr="logs-services-v2">
                {viewMode === 'grid' ? (
                    <ServicesGrid />
                ) : (
                    <LemonTable
                        columns={COLUMNS}
                        dataSource={pageRows}
                        loading={servicesDataLoading}
                        pagination={{
                            controlled: true,
                            pageSize: SERVICES_PAGE_SIZE,
                            currentPage: page,
                            entryCount: services.length,
                            onForward: () => setPage(page + 1),
                            onBackward: () => setPage(page - 1),
                            useUrl: false,
                        }}
                        emptyState={
                            searchTerm ? 'No services match your search' : 'No services found in this time range'
                        }
                        rowKey="service_name"
                        size="small"
                    />
                )}
            </div>
        </div>
    )
}
