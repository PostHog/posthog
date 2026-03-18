import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonSwitch, LemonTable, LemonTableColumns, SpinnerOverlay } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import { LogsAlertConfigurationApi, ThresholdOperatorEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { logsAlertingLogic } from './logsAlertingLogic'
import { LogsAlertStateIndicator } from './LogsAlertStateIndicator'

function formatThreshold(alert: LogsAlertConfigurationApi): string {
    const operator = alert.threshold_operator === ThresholdOperatorEnumApi.Below ? '<' : '>'
    return `${operator} ${alert.threshold_count} in ${alert.window_minutes}m`
}

export function LogsAlertList(): JSX.Element {
    const { alerts, alertsLoading } = useValues(logsAlertingLogic)
    const { setEditingAlert, setIsCreating, deleteAlert, toggleAlertEnabled } = useActions(logsAlertingLogic)

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
            render: (_, alert) => <LogsAlertStateIndicator state={alert.state} />,
        },
        {
            title: 'Threshold',
            render: (_, alert) => <span className="text-muted text-xs">{formatThreshold(alert)}</span>,
        },
        {
            title: 'Enabled',
            dataIndex: 'enabled',
            render: (_, alert) => (
                <LemonSwitch checked={alert.enabled ?? true} onChange={() => toggleAlertEnabled(alert)} />
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

    if (alertsLoading) {
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
                emptyState="No alerts configured yet."
                size="small"
            />
        </div>
    )
}
