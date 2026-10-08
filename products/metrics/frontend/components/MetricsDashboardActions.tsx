import { useActions, useValues } from 'kea'

import { IconChevronDown, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { UNFILED_DASHBOARDS_FOLDER } from 'scenes/dashboard/dashboardConstants'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { metricsDashboardImportLogic } from '../dashboardImport/metricsDashboardImportLogic'
import { metricsUsageTrackingLogic } from './metricsUsageTrackingLogic'

export function MetricsDashboardActions(): JSX.Element {
    const { isLoading } = useValues(newDashboardLogic)
    const { addDashboard, setIsLoading } = useActions(newDashboardLogic)
    const { openImportModal } = useActions(metricsDashboardImportLogic)
    const { newDashboardClicked } = useActions(metricsUsageTrackingLogic)
    const importEnabled = useFeatureFlag('METRICS_DASHBOARD_IMPORT')

    const dashboardDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Dashboard,
        AccessControlLevel.Editor
    )
    const importDisabledReason =
        dashboardDisabledReason ??
        getAccessControlDisabledReason(AccessControlResourceType.Insight, AccessControlLevel.Editor)

    const createDashboard = (): void => {
        if (isLoading) {
            return
        }
        setIsLoading(true)
        newDashboardClicked()
        addDashboard({ name: 'New metrics dashboard', show: true, _create_in_folder: UNFILED_DASHBOARDS_FOLDER })
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            {importEnabled && (
                <LemonMenu
                    items={[
                        {
                            label: 'Import from Grafana',
                            onClick: () => openImportModal('grafana'),
                            'data-attr': 'metrics-dashboard-import-grafana',
                        },
                        {
                            label: 'Import from screenshot',
                            onClick: () => openImportModal('screenshot'),
                            'data-attr': 'metrics-dashboard-import-screenshot',
                        },
                    ]}
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        sideIcon={<IconChevronDown />}
                        disabledReason={importDisabledReason}
                        data-attr="metrics-dashboard-import-menu"
                    >
                        Import
                    </LemonButton>
                </LemonMenu>
            )}
            <LemonButton
                type="primary"
                size="small"
                icon={<IconPlusSmall />}
                loading={isLoading}
                disabledReason={dashboardDisabledReason}
                onClick={createDashboard}
                data-attr="metrics-new-dashboard"
            >
                New metrics dashboard
            </LemonButton>
        </div>
    )
}
