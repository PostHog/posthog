import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSwitch, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { PlatformAlertConfigurationApi } from 'products/alerts_platform/frontend/generated/api.schemas'
import { configurationStatus } from 'products/alerts_platform/frontend/platformAlertFormat'
import { PlatformAlertStatusTag } from 'products/alerts_platform/frontend/PlatformAlertStatusTag'

import { confirmDeleteTracesAlert } from './confirmDeleteTracesAlert'
import { tracesAlertsLogic } from './tracesAlertsLogic'
import { describeTracesCondition, describeTracesScope, tracesSourceConfig } from './tracesAlertUtils'

export function TracesAlertList(): JSX.Element {
    const { alerts, alertsLoading, alertsLoaded, alertsLoadFailed, togglingAlertIds } = useValues(tracesAlertsLogic)
    const { loadAlerts, deleteAlert, toggleAlertEnabled, openCreateAlertModal, openEditAlertModal } =
        useActions(tracesAlertsLogic)
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
            render: (_, alert) => <PlatformAlertStatusTag status={configurationStatus(alert)} />,
        },
        {
            title: 'Condition',
            render: (_, alert) => {
                const config = tracesSourceConfig(alert)
                const scope = describeTracesScope(config)
                return (
                    <div className="flex flex-col gap-0.5 min-w-0 max-w-120">
                        <span className="text-xs">{describeTracesCondition(config?.condition)}</span>
                        <span className="text-secondary text-xs truncate" title={scope}>
                            {scope}
                        </span>
                    </div>
                )
            },
        },
        {
            title: 'Next check',
            dataIndex: 'next_check_at',
            render: (_, alert) =>
                alert.next_check_at ? (
                    <TZLabel time={alert.next_check_at} />
                ) : (
                    <span className="text-secondary text-xs">Not scheduled</span>
                ),
        },
        {
            title: 'Enabled',
            dataIndex: 'enabled',
            render: (_, alert) => (
                <LemonSwitch
                    checked={alert.enabled}
                    onChange={() => toggleAlertEnabled(alert)}
                    loading={togglingAlertIds.has(alert.id)}
                    disabledReason={editDisabledReason ?? undefined}
                    data-attr="traces-alert-row-toggle"
                />
            ),
        },
        {
            width: 0,
            render: (_, alert) => (
                <LemonMenu
                    items={[
                        {
                            label: 'Edit',
                            onClick: () => openEditAlertModal(alert),
                            disabledReason: editDisabledReason,
                        },
                        { label: 'View groups and history', to: urls.platformAlert(alert.id) },
                        {
                            label: 'Delete',
                            status: 'danger',
                            disabledReason: editDisabledReason,
                            'data-attr': 'traces-alert-row-delete',
                            onClick: () => confirmDeleteTracesAlert(alert, () => deleteAlert(alert)),
                        },
                    ]}
                    placement="bottom-end"
                >
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<IconEllipsis />}
                        aria-label={`More options for ${alert.name}`}
                    />
                </LemonMenu>
            ),
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
            <div className="flex justify-end">
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
                loadingSkeletonRows={3}
                emptyState="No traces alerts yet. Create one to get notified when error rates, latency or request volume cross a threshold."
                size="small"
                nouns={['alert', 'alerts']}
            />
        </div>
    )
}
