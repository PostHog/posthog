import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonSwitch, LemonTable, LemonTableColumns, SpinnerOverlay } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import {
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
    ThresholdOperatorEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { logsAlertingLogic } from './logsAlertingLogic'
import { LogsAlertStateIndicator } from './LogsAlertStateIndicator'

function formatThreshold(alert: LogsAlertConfigurationApi): string {
    const operator = alert.threshold_operator === ThresholdOperatorEnumApi.Below ? '<' : '>'
    return `${operator} ${alert.threshold_count} in ${alert.window_minutes}m`
}

export function LogsAlertList(): JSX.Element {
    const { alerts, alertsLoading, resettingAlertIds } = useValues(logsAlertingLogic)
    const { setEditingAlert, setIsCreating, deleteAlert, toggleAlertEnabled, resetAlert } =
        useActions(logsAlertingLogic)

    const columns: LemonTableColumns<LogsAlertConfigurationApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, alert) => (
                <LemonButton type="tertiary" size="small" onClick={() => setEditingAlert(alert)}>
                    {alert.name}
                </LemonButton>
            ),
        },
        {
            title: 'Status',
            dataIndex: 'state',
            render: (_, alert) => (
                <LogsAlertStateIndicator state={alert.state} lastErrorMessage={alert.last_error_message} />
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
                <LemonButton type="primary" size="small" onClick={() => setIsCreating(true)}>
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
