import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconEllipsis, IconShare } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonMenu,
    LemonSelect,
    LemonTable,
    LemonTag,
    Tooltip,
    lemonToast,
} from '@posthog/lemon-ui'
import type { LemonTableColumns } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyNumber } from 'lib/utils'
import { urls } from 'scenes/urls'

import { logsViewerModalLogic } from 'products/logs/frontend/components/LogsViewer/LogsViewerModal/logsViewerModalLogic'
import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'

import { logsServicesLogic, ServiceRow } from './logsServicesLogic'

const DATE_OPTIONS = [
    { value: '-1h', label: 'Last hour' },
    { value: '-24h', label: 'Last 24 hours' },
    { value: '-7d', label: 'Last 7 days' },
    { value: '-30d', label: 'Last 30 days' },
]

function severityMixBar(row: ServiceRow): JSX.Element {
    const b = row.severity_breakdown
    if (!b || row.log_count === 0) {
        return <span className="text-muted">-</span>
    }
    const total = b.debug + b.info + b.warn + b.error
    if (total <= 0) {
        return <span className="text-muted">-</span>
    }
    const seg = (n: number, className: string, label: string): JSX.Element | null => {
        if (n <= 0) {
            return null
        }
        const flex = Math.max(0.02, n / total)
        return (
            <Tooltip key={label} title={`${label}: ${humanFriendlyNumber(n)}`}>
                <div className={`h-2 min-w-0 ${className}`} style={{ flex }} />
            </Tooltip>
        )
    }
    return (
        <div className="flex h-2 w-28 overflow-hidden rounded bg-surface-secondary">
            {seg(b.debug, 'bg-accent-secondary', 'Debug')}
            {seg(b.info, 'bg-blue-400', 'Info')}
            {seg(b.warn, 'bg-yellow-500', 'Warn')}
            {seg(b.error, 'bg-danger', 'Error')}
        </div>
    )
}

function copyServiceDeepLink(serviceName: string): void {
    const path = combineUrl(urls.currentProject(urls.logs()), {
        activeTab: 'viewer',
        serviceNames: serviceName,
    }).url
    const full = urls.absolute(path)
    void navigator.clipboard.writeText(full).then(
        () => lemonToast.success('Link copied'),
        () => lemonToast.error('Could not copy link')
    )
}

export function LogsServices(): JSX.Element {
    const { services, servicesDataLoading, sparklineByService, dateFrom, servicesSummary } =
        useValues(logsServicesLogic)
    const { setDateFrom } = useActions(logsServicesLogic)
    const { openLogsViewerModal } = useActions(logsViewerModalLogic)
    const samplingRulesUi = useFeatureFlag(LogsFeatureFlagKeys.samplingRules)

    const presetItems = DATE_OPTIONS.map((opt) => ({
        label: opt.label,
        onClick: () => setDateFrom(opt.value),
    }))

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
            title: 'Share',
            key: 'share',
            width: 56,
            render: (_, row) => (
                <Tooltip title="Copy deep link to logs viewer with this service filter">
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconShare />}
                        onClick={() => copyServiceDeepLink(row.service_name)}
                    />
                </Tooltip>
            ),
        },
        {
            title: 'Severity mix',
            key: 'severity_mix',
            render: (_, row) => severityMixBar(row),
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
        ...(samplingRulesUi
            ? ([
                  {
                      title: 'Rules',
                      key: 'active_rules',
                      render: (_: unknown, row: ServiceRow) => {
                          const rules = row.active_rules ?? []
                          if (rules.length === 0) {
                              return <span className="text-muted">-</span>
                          }
                          return (
                              <div className="flex flex-wrap gap-1 max-w-xs">
                                  {rules.map((r) => (
                                      <LemonButton
                                          key={r.rule_id}
                                          size="xsmall"
                                          to={urls.logsSamplingDetail(r.rule_id)}
                                          className="font-normal"
                                      >
                                          {r.rule_name}
                                      </LemonButton>
                                  ))}
                              </div>
                          )
                      },
                  },
              ] as LemonTableColumns<ServiceRow>)
            : []),
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
            {servicesSummary && (
                <LemonBanner type="info" className="mb-0">
                    Top {servicesSummary.top_services_count} services by volume:{' '}
                    {servicesSummary.top_services_volume_share_pct.toFixed(1)}% of traffic in this window.
                </LemonBanner>
            )}
            <div className="flex items-center justify-between gap-2">
                <h3 className="m-0">Services</h3>
                <div className="flex items-center gap-2">
                    <LemonMenu items={presetItems} placement="bottom-end">
                        <LemonButton size="small" type="secondary" icon={<IconEllipsis />}>
                            Date presets
                        </LemonButton>
                    </LemonMenu>
                    <LemonSelect
                        size="small"
                        value={dateFrom}
                        onChange={(value) => value && setDateFrom(value)}
                        options={DATE_OPTIONS}
                    />
                </div>
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
