import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

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

/** Collapsed Rules column shows this many rule chips before "+ N more". */
const RULES_PREVIEW_COUNT = 3

const DATE_OPTIONS = [
    { value: '-1h', label: 'Last hour' },
    { value: '-24h', label: 'Last 24 hours' },
    { value: '-7d', label: 'Last 7 days' },
    { value: '-30d', label: 'Last 30 days' },
]

function severityMixTooltipBody(b: NonNullable<ServiceRow['severity_breakdown']>, total: number): JSX.Element {
    const rows: { label: string; n: number; dotClass: string }[] = [
        { label: 'Debug', n: b.debug, dotClass: 'bg-accent-secondary' },
        { label: 'Info', n: b.info, dotClass: 'bg-blue-400' },
        { label: 'Warn', n: b.warn, dotClass: 'bg-yellow-500' },
        { label: 'Error', n: b.error, dotClass: 'bg-danger' },
    ]
    return (
        <div className="text-xs space-y-1 min-w-[11rem]">
            <div className="font-semibold text-muted">Severity mix</div>
            {rows.map(({ label, n, dotClass }) => (
                <div key={label} className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-1.5">
                        <span className={`inline-block size-2 shrink-0 rounded-sm ${dotClass}`} />
                        {label}
                    </span>
                    <span className="tabular-nums text-muted">
                        {total > 0 ? ((n / total) * 100).toFixed(1) : '0.0'}% · {humanFriendlyNumber(n)}
                    </span>
                </div>
            ))}
        </div>
    )
}

function severityMixBar(row: ServiceRow): JSX.Element {
    const b = row.severity_breakdown
    if (!b || row.log_count === 0) {
        return <span className="text-muted">-</span>
    }
    const total = b.debug + b.info + b.warn + b.error
    if (total <= 0) {
        return <span className="text-muted">-</span>
    }
    const seg = (n: number, className: string): JSX.Element | null => {
        if (n <= 0) {
            return null
        }
        const flex = Math.max(0.02, n / total)
        return <div className={`h-2 min-w-0 ${className}`} style={{ flex }} />
    }
    return (
        <Tooltip title={severityMixTooltipBody(b, total)} placement="top">
            <div className="flex h-2 w-28 overflow-hidden rounded bg-surface-secondary cursor-default">
                {seg(b.debug, 'bg-accent-secondary')}
                {seg(b.info, 'bg-blue-400')}
                {seg(b.warn, 'bg-yellow-500')}
                {seg(b.error, 'bg-danger')}
            </div>
        </Tooltip>
    )
}

function ServiceRulesCell({
    row,
    rulesExpandAll,
    rulesExpandedByService,
    onToggleRow,
}: {
    row: ServiceRow
    rulesExpandAll: boolean
    rulesExpandedByService: Record<string, boolean>
    onToggleRow: (serviceName: string) => void
}): JSX.Element {
    const rules = row.active_rules ?? []
    if (rules.length === 0) {
        return <span className="text-muted">-</span>
    }

    const rowExpanded = rulesExpandAll || rulesExpandedByService[row.service_name]
    const needsTruncate = rules.length > RULES_PREVIEW_COUNT
    const showAll = rowExpanded || !needsTruncate
    const visibleRules = showAll ? rules : rules.slice(0, RULES_PREVIEW_COUNT)
    const hiddenCount = rules.length - RULES_PREVIEW_COUNT

    return (
        <div className="flex flex-col gap-1 max-w-md">
            <div className="flex flex-wrap gap-1">
                {visibleRules.map((r) => (
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
            {needsTruncate && !rowExpanded ? (
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    className="self-start font-normal"
                    onClick={() => onToggleRow(row.service_name)}
                >
                    Show {hiddenCount} more
                </LemonButton>
            ) : null}
            {needsTruncate && rowExpanded && !rulesExpandAll ? (
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    className="self-start font-normal"
                    onClick={() => onToggleRow(row.service_name)}
                >
                    Show less
                </LemonButton>
            ) : null}
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
    const samplingRulesUi = useFeatureFlag(LogsFeatureFlagKeys.dropRules)

    const [rulesExpandAll, setRulesExpandAll] = useState(false)
    const [rulesExpandedByService, setRulesExpandedByService] = useState<Record<string, boolean>>({})

    const servicesWithManyRules = useMemo(
        () => services.filter((s) => (s.active_rules?.length ?? 0) > RULES_PREVIEW_COUNT),
        [services]
    )
    const showRulesBulkControls = samplingRulesUi && servicesWithManyRules.length > 0

    useEffect(() => {
        if (servicesWithManyRules.length === 0) {
            setRulesExpandAll(false)
        }
    }, [servicesWithManyRules.length])

    const toggleServiceRulesExpanded = (serviceName: string): void => {
        setRulesExpandedByService((prev) => ({ ...prev, [serviceName]: !prev[serviceName] }))
    }

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
                      title: showRulesBulkControls ? (
                          <div className="flex items-center gap-2 min-w-0">
                              <span className="shrink-0">Rules</span>
                              <LemonButton
                                  size="xsmall"
                                  type="secondary"
                                  onClick={() => {
                                      if (rulesExpandAll) {
                                          setRulesExpandAll(false)
                                          setRulesExpandedByService({})
                                      } else {
                                          setRulesExpandAll(true)
                                          setRulesExpandedByService({})
                                      }
                                  }}
                              >
                                  {rulesExpandAll ? 'Collapse all' : 'Expand all'}
                              </LemonButton>
                          </div>
                      ) : (
                          'Rules'
                      ),
                      key: 'active_rules',
                      render: (_: unknown, row: ServiceRow) => (
                          <ServiceRulesCell
                              row={row}
                              rulesExpandAll={rulesExpandAll}
                              rulesExpandedByService={rulesExpandedByService}
                              onToggleRow={toggleServiceRulesExpanded}
                          />
                      ),
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
