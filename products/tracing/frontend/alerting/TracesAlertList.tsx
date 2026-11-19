import { useActions, useValues } from 'kea'

import { IconBell, IconEllipsis } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonSwitch,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
    LemonTag,
} from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import type { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { destinationTypeLabel } from 'products/alerts_platform/frontend/destinations/platformAlertDestinations'
import {
    PlatformAlertConfigurationApi,
    PlatformAlertDestinationTypeEnumApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'
import { PlatformAlertStateIndicator } from 'products/alerts_platform/frontend/PlatformAlertStateIndicator'
import { PlatformAlertStateTimeline } from 'products/alerts_platform/frontend/PlatformAlertStateTimeline'

import { confirmDeleteTracesAlert } from './confirmDeleteTracesAlert'
import { tracesAlertsLogic } from './tracesAlertsLogic'
import {
    SNOOZE_DURATIONS,
    describeTracesCondition,
    describeTracesScope,
    indicatorState,
    tracesSourceConfig,
} from './tracesAlertUtils'

export function TracesAlertList(): JSX.Element {
    const {
        alerts,
        alertsLoading,
        alertsLoaded,
        alertsLoadFailed,
        togglingAlertIds,
        resettingAlertIds,
        snoozingAlertIds,
        createdByFilter,
    } = useValues(tracesAlertsLogic)
    const {
        loadAlerts,
        deleteAlert,
        toggleAlertEnabled,
        resetAlert,
        snoozeAlert,
        unsnoozeAlert,
        setCreatedByFilter,
        openCreateAlertModal,
        openEditAlertModal,
        openHistoryModal,
    } = useActions(tracesAlertsLogic)
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Tracing,
        AccessControlLevel.Editor
    )

    const columns: LemonTableColumns<PlatformAlertConfigurationApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, alert) => (
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={() => openEditAlertModal(alert)}
                    disabledReason={editDisabledReason}
                    data-attr="traces-alert-row-name"
                >
                    {alert.name}
                </LemonButton>
            ),
        },
        {
            title: 'Status',
            render: (_, alert) => (
                <PlatformAlertStateIndicator
                    state={indicatorState(alert)}
                    enabled={alert.enabled}
                    firstEnabledAt={alert.created_at}
                    lastErrorMessage={alert.last_error_message}
                    snoozeUntil={alert.snooze_until}
                />
            ),
        },
        {
            title: 'Condition',
            render: (_, alert) => {
                const config = tracesSourceConfig(alert)
                const scope = describeTracesScope(config)
                return (
                    <div className="flex flex-col gap-0.5 min-w-0 max-w-80">
                        <span className="text-xs">{describeTracesCondition(config?.condition)}</span>
                        <span className="text-muted text-xs truncate" title={scope}>
                            {scope}
                        </span>
                    </div>
                )
            },
        },
        {
            title: 'Last checked',
            render: (_, alert) =>
                alert.last_checked_at ? (
                    <TZLabel time={alert.last_checked_at} />
                ) : (
                    <span className="text-muted text-xs">Never</span>
                ),
        },
        {
            title: (
                <Tooltip title="When this alert is next scheduled to be checked.">
                    <span className="cursor-help">Next check</span>
                </Tooltip>
            ),
            dataIndex: 'next_check_at',
            render: (_, alert) =>
                alert.next_check_at ? (
                    <TZLabel time={alert.next_check_at} />
                ) : (
                    <span className="text-muted text-xs">Pending</span>
                ),
        },
        {
            title: (
                <Tooltip title="Alert state over the last 24 hours. Green = OK, red = firing, orange = errored, grey = snoozed or disabled. Hover to see the state at a point in time.">
                    <span className="cursor-help">Last 24h</span>
                </Tooltip>
            ),
            render: (_, alert) => <PlatformAlertStateTimeline timeline={alert.state_timeline} className="h-6 w-72" />,
        },
        {
            title: 'Notifications',
            render: (_, alert) => {
                if (alert.destination_types.length === 0) {
                    return (
                        <div className="flex items-center gap-1">
                            <LemonTag type="warning">None</LemonTag>
                            <LemonButton
                                size="small"
                                type="tertiary"
                                icon={<IconBell />}
                                onClick={() => openEditAlertModal(alert)}
                                tooltip="No notification destinations. Click to add one."
                                disabledReason={editDisabledReason}
                            />
                        </div>
                    )
                }
                return (
                    <div className="flex items-center gap-1">
                        {alert.destination_types.map((type) => (
                            <LemonTag key={type}>
                                {destinationTypeLabel(type as PlatformAlertDestinationTypeEnumApi)}
                            </LemonTag>
                        ))}
                        <LemonButton
                            size="small"
                            type="tertiary"
                            icon={<IconBell />}
                            onClick={() => openEditAlertModal(alert)}
                            tooltip="Configure notifications"
                            disabledReason={editDisabledReason}
                        />
                    </div>
                )
            },
        },
        createdByColumn() as unknown as LemonTableColumn<
            PlatformAlertConfigurationApi,
            keyof PlatformAlertConfigurationApi | undefined
        >,
        {
            title: 'Enabled',
            dataIndex: 'enabled',
            render: (_, alert) => (
                <LemonSwitch
                    checked={alert.enabled}
                    onChange={() => toggleAlertEnabled(alert)}
                    loading={togglingAlertIds.has(alert.id)}
                    disabledReason={
                        editDisabledReason ??
                        (alert.check_status === 'broken' ? 'Reset this alert to re-enable checks' : undefined)
                    }
                    data-attr="traces-alert-row-toggle"
                />
            ),
        },
        {
            width: 0,
            render: (_, alert) => {
                const isSnoozed = !!alert.snooze_until && new Date(alert.snooze_until) > new Date()
                const isSnoozing = snoozingAlertIds.has(alert.id)
                const isResetting = resettingAlertIds.has(alert.id)
                let snoozeMenuItem: LemonMenuItems[number] | false = false
                if (alert.enabled && isSnoozed) {
                    snoozeMenuItem = {
                        label: isSnoozing ? 'Unsnoozing…' : 'Unsnooze',
                        disabledReason: editDisabledReason ?? (isSnoozing ? 'Updating snooze' : undefined),
                        onClick: () => unsnoozeAlert(alert.id),
                    }
                } else if (alert.enabled) {
                    snoozeMenuItem = {
                        label: isSnoozing ? 'Snoozing…' : 'Snooze',
                        disabledReason: editDisabledReason ?? (isSnoozing ? 'Updating snooze' : undefined),
                        items: SNOOZE_DURATIONS.map((duration) => ({
                            label: duration.label,
                            onClick: () => snoozeAlert(alert.id, duration.minutes),
                        })),
                    }
                }
                const menuItems: LemonMenuItems = [
                    { label: 'Edit', onClick: () => openEditAlertModal(alert), disabledReason: editDisabledReason },
                    { label: 'View history', onClick: () => openHistoryModal(alert) },
                    snoozeMenuItem,
                    alert.check_status === 'broken' && {
                        label: isResetting ? 'Resetting…' : 'Reset alert',
                        disabledReason: editDisabledReason ?? (isResetting ? 'Reset in progress' : undefined),
                        onClick: () => resetAlert(alert.id),
                    },
                    {
                        label: 'Delete',
                        status: 'danger',
                        disabledReason: editDisabledReason,
                        'data-attr': 'traces-alert-row-delete',
                        onClick: () => confirmDeleteTracesAlert(alert, () => deleteAlert(alert)),
                    },
                ]
                return (
                    <LemonMenu items={menuItems} placement="bottom-end">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconEllipsis />}
                            aria-label={`More options for ${alert.name}`}
                        />
                    </LemonMenu>
                )
            },
        },
    ]

    if (alertsLoadFailed && !alertsLoaded) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadAlerts() }}>
                Could not load traces alerts. Retry, and if it keeps failing, contact support.
            </LemonBanner>
        )
    }

    return (
        <div className="space-y-2">
            <div className="flex justify-end gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                    <span>Created by:</span>
                    <MemberSelect value={createdByFilter} onChange={(user) => setCreatedByFilter(user?.uuid ?? null)} />
                </div>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={openCreateAlertModal}
                    disabledReason={editDisabledReason}
                    data-attr="traces-alerts-new"
                >
                    New alert
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={alerts}
                rowKey="id"
                loading={alertsLoading && !alertsLoaded}
                loadingSkeletonRows={5}
                emptyState={
                    createdByFilter
                        ? 'No alerts match this filter.'
                        : 'No traces alerts yet. Create one to get notified when error rates, latency or request volume cross a threshold.'
                }
                size="small"
                pagination={{ pageSize: 30 }}
                nouns={['alert', 'alerts']}
            />
        </div>
    )
}
