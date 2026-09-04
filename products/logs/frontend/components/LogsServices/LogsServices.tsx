import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconShare } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'
import type { LemonTableColumns } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { logsViewerModalLogic } from 'products/logs/frontend/components/LogsViewer/LogsViewerModal/logsViewerModalLogic'

import { logsServicesLogic, SERVICES_PAGE_SIZE, ServiceRow } from './logsServicesLogic'
import { copyServiceDeepLink } from './serviceViewerUrl'

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

export function LogsServices(): JSX.Element {
    const {
        services,
        pageRows,
        page,
        searchTerm,
        servicesDataLoading,
        sorting,
        sparklineByService,
        dateFrom,
        servicesSummary,
        totalServices,
    } = useValues(logsServicesLogic)
    const { setDateFrom, setPage, setSearchTerm, setSorting } = useActions(logsServicesLogic)
    const { openLogsViewerModal } = useActions(logsViewerModalLogic)

    const [rulesExpandAll, setRulesExpandAll] = useState(false)
    const [rulesExpandedByService, setRulesExpandedByService] = useState<Record<string, boolean>>({})

    const servicesWithManyRules = useMemo(
        () => services.filter((s) => (s.active_rules?.length ?? 0) > RULES_PREVIEW_COUNT),
        [services]
    )
    const showRulesBulkControls = servicesWithManyRules.length > 0

    useEffect(() => {
        if (servicesWithManyRules.length === 0) {
            setRulesExpandAll(false)
        }
    }, [servicesWithManyRules.length])

    const toggleServiceRulesExpanded = (serviceName: string): void => {
        setRulesExpandedByService((prev) => ({ ...prev, [serviceName]: !prev[serviceName] }))
    }

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
            sorter: true,
        },
        {
            title: 'Log volume',
            dataIndex: 'log_count',
            render: (_, row) => humanFriendlyNumber(row.log_count),
            sorter: true,
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
            sorter: true,
            align: 'right',
        },
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
            render: (_, row) => (
                <ServiceRulesCell
                    row={row}
                    rulesExpandAll={rulesExpandAll}
                    rulesExpandedByService={rulesExpandedByService}
                    onToggleRow={toggleServiceRulesExpanded}
                />
            ),
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
                        <Sparkline data={sparkline.values} labels={sparkline.labels} className="w-full h-full" />
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
            {totalServices > services.length && (
                <LemonBanner type="info" className="mb-0">
                    Showing the top {humanFriendlyNumber(services.length)} of {humanFriendlyNumber(totalServices)}{' '}
                    {searchTerm ? 'matching services' : 'services'} by volume.{' '}
                    {searchTerm ? 'Refine your search to see the rest.' : 'Use search to find the rest.'}
                </LemonBanner>
            )}
            <div className="flex items-center justify-between gap-2">
                <h3 className="m-0">Services</h3>
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
            {/* The scene container is a fixed height, so this region scrolls. Without it the
                table is squeezed and clips its own last rows and the pagination control. */}
            <div className="flex-1 min-h-0 overflow-y-auto">
                {/* Pagination and sorting are controlled by the logic (which passes in the
                    pre-sorted page slice) so it knows which rows are visible and can lazy-load
                    their sparklines; the backend only sparklines the top rows per request. */}
                <LemonTable
                    columns={columns}
                    dataSource={pageRows}
                    loading={servicesDataLoading}
                    sorting={sorting}
                    onSort={(newSorting) => setSorting(newSorting)}
                    useURLForSorting={false}
                    pagination={{
                        controlled: true,
                        pageSize: SERVICES_PAGE_SIZE,
                        currentPage: page,
                        entryCount: services.length,
                        onForward: () => setPage(page + 1),
                        onBackward: () => setPage(page - 1),
                        useUrl: false,
                    }}
                    emptyState={searchTerm ? 'No services match your search' : 'No services found in this time range'}
                    rowKey="service_name"
                    size="small"
                />
            </div>
        </div>
    )
}
