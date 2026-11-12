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

import { confirmDeleteMetricsAlert } from './confirmDeleteMetricsAlert'
import { metricsAlertingLogic } from './metricsAlertingLogic'
import { describeMetricsCondition, metricsSourceConfig } from './metricsAlertUtils'

export function MetricsAlertList(): JSX.Element {
    const { alerts, alertsLoading, alertsLoaded, alertsLoadFailed, togglingAlertIds } = useValues(metricsAlertingLogic)
    const { loadAlerts, deleteAlert, toggleAlertEnabled } = useActions(metricsAlertingLogic)
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Metrics,
        AccessControlLevel.Editor
    )

    const columns: LemonTableColumns<PlatformAlertConfigurationApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, alert) => <span className="font-semibold">{alert.name}</span>,
        },
        {
            title: 'Status',
            render: (_, alert) => <PlatformAlertStatusTag status={configurationStatus(alert)} />,
        },
        {
            title: 'Condition',
            render: (_, alert) => {
                const config = metricsSourceConfig(alert)
                return (
                    <div className="flex flex-col gap-0.5 max-w-80">
                        <code className="block text-xs truncate" title={config?.query}>
                            {config?.query ?? 'Unknown query'}
                        </code>
                        <span className="text-secondary text-xs">{describeMetricsCondition(config?.condition)}</span>
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
                    data-attr="metrics-alert-row-toggle"
                />
            ),
        },
        {
            width: 0,
            render: (_, alert) => (
                <LemonMenu
                    items={[
                        { label: 'View groups and history', to: urls.platformAlert(alert.id) },
                        {
                            label: 'Delete',
                            status: 'danger',
                            disabledReason: editDisabledReason,
                            'data-attr': 'metrics-alert-row-delete',
                            onClick: () => confirmDeleteMetricsAlert(alert, () => deleteAlert(alert)),
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
                Could not load metrics alerts. Retry, and if it keeps failing, contact support.
            </LemonBanner>
        )
    }

    return (
        <LemonTable
            columns={columns}
            dataSource={alerts}
            rowKey="id"
            loading={alertsLoading && !alertsLoaded}
            loadingSkeletonRows={3}
            emptyState="No metrics alerts yet."
            size="small"
            nouns={['alert', 'alerts']}
        />
    )
}
