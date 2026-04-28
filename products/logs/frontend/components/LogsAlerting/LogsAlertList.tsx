import { useActions, useValues } from 'kea'

import { IconBell } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonSwitch,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    SpinnerOverlay,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import IconSlack from 'public/services/slack.png'
import IconWebhook from 'public/services/webhook.svg'

import {
    NotificationDestinationTypeEnumApi,
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
    ThresholdOperatorEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { logsAlertingLogic } from './logsAlertingLogic'
import { LogsAlertStateIndicator } from './LogsAlertStateIndicator'
import { LogsAlertStateTimeline } from './LogsAlertStateTimeline'
import { SNOOZE_DURATIONS } from './logsAlertUtils'

function formatThreshold(alert: LogsAlertConfigurationApi): string {
    const operator = alert.threshold_operator === ThresholdOperatorEnumApi.Below ? '<' : '>'
    return `${operator} ${alert.threshold_count} in ${alert.window_minutes}m`
}

export function LogsAlertList(): JSX.Element {
    const { alerts, alertsLoading, resettingAlertIds } = useValues(logsAlertingLogic)
    const {
        setEditingAlert,
        deleteAlert,
        toggleAlertEnabled,
        resetAlert,
        setViewingHistoryAlert,
        snoozeAlert,
        unsnoozeAlert,
    } = useActions(logsAlertingLogic)

    const columns: LemonTableColumns<LogsAlertConfigurationApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, alert) => (
                <LemonButton type="tertiary" size="small" to={urls.logsAlertDetail(alert.id)}>
                    {alert.name}
                </LemonButton>
            ),
        },
        {
            title: 'Status',
            dataIndex: 'state',
            render: (_, alert) => (
                <LogsAlertStateIndicator
                    state={alert.state}
                    enabled={alert.enabled ?? true}
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
                <Tooltip title="Alert state over the last 24 hours. Green = OK, red = firing, orange = resolving/errored, grey = snoozed or disabled. Hover to see the state at a point in time.">
                    <span className="cursor-help">Last 24h</span>
                </Tooltip>
            ),
            render: (_, alert) => <LogsAlertStateTimeline timeline={alert.state_timeline} className="h-6 w-72" />,
        },
        {
            title: 'Notifications',
            dataIndex: 'destination_types',
            render: (_, alert) => {
                const types = alert.destination_types ?? []
                const notifUrl = urls.logsAlertDetail(alert.id, 'notifications')
                if (types.length === 0) {
                    return (
                        <div className="flex items-center gap-1">
                            <LemonTag type="warning">None</LemonTag>
                            <LemonButton
                                size="small"
                                type="tertiary"
                                icon={
                                    <span className="relative inline-flex text-danger">
                                        <IconBell />
                                        <span aria-hidden className="absolute inset-0 flex items-center justify-center">
                                            <span className="block h-px w-[140%] rotate-45 bg-danger" />
                                        </span>
                                    </span>
                                }
                                to={notifUrl}
                                tooltip="No notification destinations configured — click to configure"
                            />
                        </div>
                    )
                }
                return (
                    <div className="flex items-center gap-1">
                        <div className="flex gap-1">
                            {types.includes(NotificationDestinationTypeEnumApi.Slack) && (
                                <LemonTag>
                                    <img src={IconSlack} alt="" className="h-3 w-3 object-contain" />
                                    Slack
                                </LemonTag>
                            )}
                            {types.includes(NotificationDestinationTypeEnumApi.Webhook) && (
                                <LemonTag>
                                    <img src={IconWebhook} alt="" className="h-3 w-3 object-contain" />
                                    Webhook
                                </LemonTag>
                            )}
                        </div>
                        <LemonButton
                            size="small"
                            type="tertiary"
                            icon={<IconBell />}
                            to={notifUrl}
                            tooltip="Configure notifications"
                        />
                    </div>
                )
            },
        },
        {
            title: 'Created by',
            dataIndex: 'created_by',
            render: (_, alert) => (
                <span className="text-muted text-xs">
                    {alert.created_by?.first_name || alert.created_by?.email || '—'}
                </span>
            ),
        },
        {
            title: 'Enabled',
            dataIndex: 'enabled',
            render: (_, alert) => (
                <LemonSwitch
                    checked={alert.enabled ?? true}
                    onChange={() => toggleAlertEnabled(alert)}
                    disabledReason={
                        alert.state === LogsAlertConfigurationStateEnumApi.Broken
                            ? 'Reset this alert to re-enable checks'
                            : undefined
                    }
                />
            ),
        },
        {
            title: '',
            render: (_, alert) => (
                <More
                    overlay={
                        <LemonMenuOverlay
                            items={[
                                {
                                    label: 'Edit',
                                    onClick: () => setEditingAlert(alert),
                                },
                                {
                                    label: 'View history',
                                    onClick: () => setViewingHistoryAlert(alert),
                                },
                                alert.state === LogsAlertConfigurationStateEnumApi.Snoozed
                                    ? {
                                          label: 'Unsnooze',
                                          onClick: () => unsnoozeAlert(alert.id),
                                      }
                                    : {
                                          label: 'Snooze',
                                          items: SNOOZE_DURATIONS.map((d) => ({
                                              label: d.label,
                                              onClick: () => snoozeAlert(alert.id, d.minutes),
                                          })),
                                      },
                                ...(alert.state === LogsAlertConfigurationStateEnumApi.Broken
                                    ? [
                                          {
                                              label: resettingAlertIds.has(alert.id) ? 'Resetting…' : 'Reset alert',
                                              onClick: () => resetAlert(alert.id),
                                              disabledReason: resettingAlertIds.has(alert.id)
                                                  ? 'Reset in progress'
                                                  : undefined,
                                          },
                                      ]
                                    : []),
                                {
                                    label: 'Delete',
                                    status: 'danger',
                                    onClick: () => {
                                        LemonDialog.open({
                                            title: `Delete "${alert.name}"?`,
                                            description:
                                                'This alert will be permanently deleted. This action cannot be undone.',
                                            primaryButton: {
                                                children: 'Delete',
                                                type: 'primary',
                                                status: 'danger',
                                                onClick: () => deleteAlert(alert.id),
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                            },
                                        })
                                    },
                                },
                            ]}
                        />
                    }
                />
            ),
        },
    ]

    if (alertsLoading && alerts.length === 0) {
        return <SpinnerOverlay />
    }

    return (
        <div className="space-y-2">
            <div className="flex justify-end">
                <LemonButton type="primary" size="small" to={urls.logsAlertNew()}>
                    New alert
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={alerts}
                rowKey="id"
                loading={alertsLoading}
                emptyState="No alerts configured yet."
                size="small"
            />
        </div>
    )
}
