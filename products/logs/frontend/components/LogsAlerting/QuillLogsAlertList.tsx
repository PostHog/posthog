import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { IconBell, IconEllipsis, IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    DataTableProps,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    Skeleton,
    Switch,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { AnalyticsOwner } from 'scenes/analytics/AnalyticsOwner'
import { urls } from 'scenes/urls'

import { PlatformAlertStateTimeline } from 'products/alerts_platform/frontend/PlatformAlertStateTimeline'
import {
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { confirmDeleteLogsAlert } from './confirmDeleteLogsAlert'
import { formatThreshold } from './formatLogsAlertThreshold'
import { DESTINATION_TAGS } from './logsAlertDestinationTags'
import { logsAlertingLogic } from './logsAlertingLogic'
import { SNOOZE_DURATIONS } from './logsAlertUtils'
import { QuillLogsAlertStateIndicator } from './QuillLogsAlertStateIndicator'

const PAGE_SIZE = 30

function HeaderWithTooltip({ label, help }: { label: string; help: string }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="cursor-help" />}>{label}</TooltipTrigger>
            <TooltipContent className="max-w-80">{help}</TooltipContent>
        </Tooltip>
    )
}

export function QuillLogsAlertList(): JSX.Element {
    const { alerts, alertsLoading, resettingAlertIds, snoozingAlertIds, createdByFilter } = useValues(logsAlertingLogic)
    const {
        setCreatedByFilter,
        deleteAlert,
        toggleAlertEnabled,
        resetAlert,
        snoozeAlert,
        unsnoozeAlert,
        openCreateAlertModal,
        openEditAlertModal,
    } = useActions(logsAlertingLogic)

    const columns = useMemo<DataTableProps<LogsAlertConfigurationApi, unknown>['columns']>(
        () => [
            {
                id: 'name',
                header: 'Name',
                enableSorting: false,
                meta: { expand: true },
                cell: ({ row }) => (
                    <Button variant="link-foreground" size="sm" onClick={() => openEditAlertModal(row.original)}>
                        {row.original.name}
                    </Button>
                ),
            },
            {
                id: 'state',
                header: 'Status',
                enableSorting: false,
                cell: ({ row }) => (
                    <QuillLogsAlertStateIndicator
                        state={row.original.state}
                        enabled={row.original.enabled === true}
                        firstEnabledAt={row.original.first_enabled_at}
                        lastErrorMessage={row.original.last_error_message}
                        snoozeUntil={row.original.snooze_until}
                    />
                ),
            },
            {
                id: 'threshold',
                header: 'Threshold',
                enableSorting: false,
                cell: ({ row }) => (
                    <Text size="xs" variant="muted" render={<span />} className="whitespace-nowrap">
                        {formatThreshold(row.original)}
                    </Text>
                ),
            },
            {
                id: 'last_checked_at',
                header: 'Last checked',
                enableSorting: false,
                cell: ({ row }) =>
                    row.original.last_checked_at ? (
                        <TZLabel time={row.original.last_checked_at} />
                    ) : (
                        <Text size="xs" variant="muted" render={<span />}>
                            Never
                        </Text>
                    ),
            },
            {
                id: 'next_check_at',
                header: () => (
                    <HeaderWithTooltip
                        label="Next check"
                        help="When this alert is next scheduled to be evaluated. Alerts of the same cadence are spread across the cadence period to smooth load on the database."
                    />
                ),
                enableSorting: false,
                cell: ({ row }) =>
                    row.original.next_check_at ? (
                        <TZLabel time={row.original.next_check_at} />
                    ) : (
                        <Text size="xs" variant="muted" render={<span />}>
                            Pending
                        </Text>
                    ),
            },
            {
                id: 'state_timeline',
                header: () => (
                    <HeaderWithTooltip
                        label="Last 24h"
                        help="Alert state over the last 24 hours. Green = OK, red = firing, orange = resolving/errored, grey = snoozed or disabled. Hover to see the state at a point in time."
                    />
                ),
                enableSorting: false,
                cell: ({ row }) => (
                    <PlatformAlertStateTimeline timeline={row.original.state_timeline} className="h-6 w-72" />
                ),
            },
            {
                id: 'destination_types',
                header: 'Notifications',
                enableSorting: false,
                cell: ({ row }) => {
                    const types = row.original.destination_types ?? []
                    const notificationsUrl = urls.logsAlertDetail(row.original.id, 'notifications')

                    if (types.length === 0) {
                        return (
                            <div className="flex items-center gap-1">
                                <Badge variant="warning">None</Badge>
                                <Button
                                    size="icon"
                                    indicator="warning"
                                    aria-label="No notification destinations configured. Click to configure."
                                    tooltip="No notification destinations configured. Click to configure."
                                    nativeButton={false}
                                    render={<LinkPrimitive to={notificationsUrl} />}
                                >
                                    <IconBell />
                                </Button>
                            </div>
                        )
                    }

                    return (
                        <div className="flex items-center gap-1">
                            <div className="flex gap-1">
                                {DESTINATION_TAGS.filter(({ type }) => types.includes(type)).map(
                                    ({ type, label, icon }) => (
                                        <Badge key={type}>
                                            <img src={icon} alt="" className="size-3 object-contain" />
                                            {label}
                                        </Badge>
                                    )
                                )}
                            </div>
                            <Button
                                size="icon"
                                aria-label="Configure notifications"
                                tooltip="Configure notifications"
                                nativeButton={false}
                                render={<LinkPrimitive to={notificationsUrl} />}
                            >
                                <IconBell />
                            </Button>
                        </div>
                    )
                },
            },
            {
                id: 'created_by',
                header: 'Created by',
                enableSorting: false,
                cell: ({ row }) => {
                    const createdBy = row.original.created_by

                    return (
                        <AnalyticsOwner
                            owner={createdBy ? { ...createdBy, first_name: createdBy.first_name ?? '' } : null}
                            className="max-w-40"
                        />
                    )
                },
            },
            {
                id: 'enabled',
                header: 'Enabled',
                enableSorting: false,
                cell: ({ row }) => (
                    <Switch
                        checked={row.original.enabled === true}
                        onCheckedChange={() => toggleAlertEnabled(row.original)}
                        disabledReason={
                            row.original.state === LogsAlertConfigurationStateEnumApi.Broken
                                ? 'Reset this alert to re-enable checks'
                                : undefined
                        }
                        aria-label={`Enable ${row.original.name}`}
                        data-attr="logs-alert-row-toggle"
                    />
                ),
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { align: 'right' },
                cell: ({ row }) => {
                    const alert = row.original
                    const isResetting = resettingAlertIds.has(alert.id)
                    const isSnoozing = snoozingAlertIds.has(alert.id)
                    const isEnabled = alert.enabled === true
                    const isSnoozed = alert.state === LogsAlertConfigurationStateEnumApi.Snoozed

                    return (
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={
                                    <Button
                                        size="icon"
                                        aria-label={`More options for ${alert.name}`}
                                        tooltip={`More options for ${alert.name}`}
                                    />
                                }
                            >
                                <IconEllipsis />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={() => openEditAlertModal(alert)}>Edit</DropdownMenuItem>
                                <DropdownMenuItem
                                    onClick={() => router.actions.push(urls.logsAlertDetail(alert.id, 'history'))}
                                >
                                    View history
                                </DropdownMenuItem>
                                {isEnabled && isSnoozed && (
                                    <DropdownMenuItem
                                        onClick={() => unsnoozeAlert(alert.id)}
                                        disabledReason={isSnoozing ? 'Updating snooze' : undefined}
                                    >
                                        {isSnoozing ? 'Unsnoozing…' : 'Unsnooze'}
                                    </DropdownMenuItem>
                                )}
                                {isEnabled && !isSnoozed && (
                                    <DropdownMenuSub>
                                        <DropdownMenuSubTrigger
                                            disabledReason={isSnoozing ? 'Updating snooze' : undefined}
                                        >
                                            {isSnoozing ? 'Snoozing…' : 'Snooze'}
                                        </DropdownMenuSubTrigger>
                                        <DropdownMenuSubContent>
                                            {SNOOZE_DURATIONS.map((duration) => (
                                                <DropdownMenuItem
                                                    key={duration.minutes}
                                                    onClick={() => snoozeAlert(alert.id, duration.minutes)}
                                                >
                                                    {duration.label}
                                                </DropdownMenuItem>
                                            ))}
                                        </DropdownMenuSubContent>
                                    </DropdownMenuSub>
                                )}
                                {alert.state === LogsAlertConfigurationStateEnumApi.Broken && (
                                    <DropdownMenuItem
                                        onClick={() => resetAlert(alert.id)}
                                        disabledReason={isResetting ? 'Reset in progress' : undefined}
                                    >
                                        {isResetting ? 'Resetting…' : 'Reset alert'}
                                    </DropdownMenuItem>
                                )}
                                <DropdownMenuItem
                                    variant="destructive"
                                    onClick={() => confirmDeleteLogsAlert(alert, deleteAlert)}
                                    data-attr="logs-alert-row-delete"
                                >
                                    Delete
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )
                },
            },
        ],
        [
            resettingAlertIds,
            snoozingAlertIds,
            deleteAlert,
            toggleAlertEnabled,
            resetAlert,
            snoozeAlert,
            unsnoozeAlert,
            openEditAlertModal,
        ]
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-end gap-2">
                <div className="flex items-center gap-2">
                    <Text size="xs" render={<span />}>
                        Created by:
                    </Text>
                    <MemberSelect value={createdByFilter} onChange={(user) => setCreatedByFilter(user?.uuid ?? null)} />
                </div>
                <Button variant="primary" onClick={openCreateAlertModal} data-attr="logs-alerts-new">
                    <IconPlus />
                    New alert
                </Button>
            </div>
            {alertsLoading && alerts.length === 0 ? (
                <div className="flex flex-col gap-2">
                    {[0, 1, 2, 3, 4].map((index) => (
                        <Skeleton key={index} className="h-8 w-full" />
                    ))}
                </div>
            ) : (
                <DataTable
                    columns={columns}
                    data={alerts}
                    getRowId={(alert) => alert.id}
                    pageSize={PAGE_SIZE}
                    fullWidth
                    empty={
                        <Text size="xs" variant="muted" render={<span />}>
                            {createdByFilter ? 'No alerts match this filter.' : 'No alerts configured yet.'}
                        </Text>
                    }
                />
            )}
        </div>
    )
}
