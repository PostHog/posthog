import { useActions, useValues } from 'kea'

import { LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'
import type { LemonTableColumns } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { humanFriendlyNumber } from 'lib/utils'

import { logsViewerModalLogic } from 'products/logs/frontend/components/LogsViewer/LogsViewerModal/logsViewerModalLogic'

import { logsServicesLogic, ServiceRow } from './logsServicesLogic'

const DATE_OPTIONS = [
    { value: '-1h', label: 'Last hour' },
    { value: '-24h', label: 'Last 24 hours' },
    { value: '-7d', label: 'Last 7 days' },
    { value: '-30d', label: 'Last 30 days' },
]

export function LogsServices(): JSX.Element {
    const { services, servicesDataLoading, sparklineByService, dateFrom } = useValues(logsServicesLogic)
    const { setDateFrom } = useActions(logsServicesLogic)
    const { openLogsViewerModal } = useActions(logsViewerModalLogic)

    const columns: LemonTableColumns<ServiceRow> = [
        {
            title: 'Service name',
            dataIndex: 'service_name',
            render: (_, row) => (
                <span
                    className="font-medium cursor-pointer text-link"
                    onClick={() =>
                        openLogsViewerModal({
                            fullScreen: false,
                            initialFilters: { serviceNames: [row.service_name] },
                        })
                    }
                >
                    {row.service_name}
                </span>
            ),
            sorter: (a, b) => a.service_name.localeCompare(b.service_name),
        },
        {
            title: 'Log volume',
            dataIndex: 'log_count',
            render: (_, row) => humanFriendlyNumber(row.log_count),
            sorter: (a, b) => a.log_count - b.log_count,
            align: 'right',
        },
        {
            title: 'Error rate',
            dataIndex: 'error_rate',
            render: (_, row) => {
                const pct = (row.error_rate * 100).toFixed(1)
                const type = row.error_rate > 0.1 ? 'danger' : row.error_rate > 0.01 ? 'warning' : 'success'
                return <LemonTag type={type}>{pct}%</LemonTag>
            },
            sorter: (a, b) => a.error_rate - b.error_rate,
            align: 'right',
        },
        {
            title: 'Volume trend',
            key: 'sparkline',
            render: (_, row) => {
                const sparkline = sparklineByService[row.service_name]
                if (!sparkline || sparkline.values.length === 0) {
                    return <span className="text-muted">-</span>
                }
                return (
                    <div className="w-24 h-6">
                        <Sparkline
                            data={sparkline.values}
                            labels={sparkline.labels}
                            className="w-full h-full"
                            maximumIndicator={false}
                        />
                    </div>
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-2 py-2 flex-1 min-h-0">
            <div className="flex items-center justify-between">
                <h3 className="m-0">Services</h3>
                <LemonSelect
                    size="small"
                    value={dateFrom}
                    onChange={(value) => value && setDateFrom(value)}
                    options={DATE_OPTIONS}
                />
            </div>
            <LemonTable
                columns={columns}
                dataSource={services}
                loading={servicesDataLoading}
                defaultSorting={{ columnKey: 'log_count', order: -1 }}
                emptyState="No services found in this time range"
                rowKey="service_name"
                size="small"
            />
        </div>
    )
}
