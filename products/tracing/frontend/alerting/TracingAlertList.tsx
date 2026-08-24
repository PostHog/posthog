import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonSwitch,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
} from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import type { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import {
    LogsAlertConfigurationStateEnumApi as TracingAlertConfigurationStateEnumApi,
    LogsAlertThresholdOperatorEnumApi as TracingAlertThresholdOperatorEnumApi,
    TracingAlertConfigurationApi,
} from 'products/tracing/frontend/generated/api.schemas'

import { tracingAlertingLogic } from './tracingAlertingLogic'
import { TracingAlertStateIndicator } from './TracingAlertStateIndicator'
import { TracingAlertStateTimeline } from './TracingAlertStateTimeline'
import { SNOOZE_DURATIONS } from './tracingAlertUtils'

function formatThreshold(alert: TracingAlertConfigurationApi): string {
    const operator = alert.threshold_operator === TracingAlertThresholdOperatorEnumApi.Below ? '<' : '>'
    return `${operator} ${alert.threshold_count} in ${alert.window_minutes}m`
}

export function TracingAlertList(): JSX.Element {
    const { alerts, alertsLoading, resettingAlertIds, snoozingAlertIds, createdByFilter } =
        useValues(tracingAlertingLogic)
    const {
        setCreatedByFilter,
        deleteAlert,
        toggleAlertEnabled,
        resetAlert,
        snoozeAlert,
        unsnoozeAlert,
        openCreateAlertModal,
        openEditAlertModal,
    } = useActions(tracingAlertingLogic)

    const columns: LemonTableColumns<TracingAlertConfigurationApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, alert) => (
                <LemonButton type="tertiary" size="small" onClick={() => openEditAlertModal(alert)}>
                    {alert.name}
                </LemonButton>
            ),
        },
        {
            title: 'Status',
            dataIndex: 'state',
            render: (_, alert) => (
                <TracingAlertStateIndicator
                    state={alert.state}
                    enabled={alert.enabled === true}
                    firstEnabledAt={alert.first_enabled_at}
                    lastErrorMessage={alert.last_error_message}
                    snoozeUntil={alert.snooze_until}
                />
            ),
        },
        {
            title: 'Threshold',
            render: (_, alert) => <span className="text-muted text-xs">{formatThreshold(alert)}</span>,
        },
        {
            title: 'Last checked',
            dataIndex: 'last_checked_at',
            render: (_, alert) =>
                alert.last_checked_at ? (
                    <TZLabel time={alert.last_checked_at} />
                ) : (
                    <span className="text-muted text-xs">Never</span>
                ),
        },
        {
            title: (
                <Tooltip title="When this alert is next scheduled to be evaluated. Alerts of the same cadence are spread across the cadence period to smooth load on the database.">
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
                <Tooltip title="Alert state over the last 24 hours. Green = OK, red = firing, orange = resolving/errored, grey = snoozed or disabled. Hover to see the state at a point in time.">
                    <span className="cursor-help">Last 24h</span>
                </Tooltip>
            ),
            render: (_, alert) => <TracingAlertStateTimeline timeline={alert.state_timeline} className="h-6 w-72" />,
        },
        createdByColumn() as unknown as LemonTableColumn<
            TracingAlertConfigurationApi,
            keyof TracingAlertConfigurationApi | undefined
        >,
        {
            title: 'Enabled',
            dataIndex: 'enabled',
            render: (_, alert) => (
                <LemonSwitch
                    checked={alert.enabled === true}
                    onChange={() => toggleAlertEnabled(alert)}
                    disabledReason={
                        alert.state === TracingAlertConfigurationStateEnumApi.Broken
                            ? 'Reset this alert to re-enable checks'
                            : undefined
                    }
                    data-attr="tracing-alert-row-toggle"
                />
            ),
        },
        {
            title: '',
            render: (_, alert) => {
                const isResetting = resettingAlertIds.has(alert.id)
                const isSnoozing = snoozingAlertIds.has(alert.id)
                let snoozeMenuItem: LemonMenuItems[number] | false = false
                if (alert.enabled === true && alert.state === TracingAlertConfigurationStateEnumApi.Snoozed) {
                    snoozeMenuItem = {
                        label: isSnoozing ? 'Unsnoozing…' : 'Unsnooze',
                        disabledReason: isSnoozing ? 'Updating snooze' : undefined,
                        onClick: () => unsnoozeAlert(alert.id),
                    }
                } else if (alert.enabled === true) {
                    snoozeMenuItem = {
                        label: isSnoozing ? 'Snoozing…' : 'Snooze',
                        disabledReason: isSnoozing ? 'Updating snooze' : undefined,
                        items: SNOOZE_DURATIONS.map((duration) => ({
                            label: duration.label,
                            onClick: () => snoozeAlert(alert.id, duration.minutes),
                        })),
                    }
                }
                const menuItems: LemonMenuItems = [
                    { label: 'Edit', onClick: () => openEditAlertModal(alert) },
                    snoozeMenuItem,
                    alert.state === TracingAlertConfigurationStateEnumApi.Broken && {
                        label: isResetting ? 'Resetting…' : 'Reset alert',
                        disabledReason: isResetting ? 'Reset in progress' : undefined,
                        onClick: () => resetAlert(alert.id),
                    },
                    {
                        label: 'Delete',
                        status: 'danger',
                        'data-attr': 'tracing-alert-row-delete',
                        onClick: () => {
                            LemonDialog.open({
                                title: `Delete "${alert.name}"?`,
                                description: 'This alert will be permanently deleted. This action cannot be undone.',
                                primaryButton: {
                                    children: 'Delete',
                                    type: 'primary',
                                    status: 'danger',
                                    onClick: () => deleteAlert(alert.id),
                                    'data-attr': 'tracing-alert-delete-confirm',
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        },
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
                    icon={<IconPlus />}
                    onClick={openCreateAlertModal}
                    data-attr="tracing-alerts-new"
                >
                    New alert
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={alerts}
                rowKey="id"
                loading={alertsLoading}
                loadingSkeletonRows={5}
                emptyState={createdByFilter ? 'No alerts match this filter.' : 'No alerts configured yet.'}
                size="small"
                pagination={{ pageSize: 30 }}
                nouns={['alert', 'alerts']}
            />
        </div>
    )
}
