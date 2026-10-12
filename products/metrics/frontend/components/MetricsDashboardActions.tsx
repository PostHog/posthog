import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconChevronDown, IconPlusSmall, IconWarning } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItem, Spinner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { UNFILED_DASHBOARDS_FOLDER } from 'scenes/dashboard/dashboardConstants'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { DashboardImportApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsDashboardImportLogic } from '../dashboardImport/metricsDashboardImportLogic'
import { metricsUsageTrackingLogic } from './metricsUsageTrackingLogic'

const MAX_LISTED_IMPORTS = 5

function importStatusLine(dashboardImport: DashboardImportApi): string {
    if (dashboardImport.status === 'running') {
        const panels = dashboardImport.panel_progress
        const settled = panels.filter((panel) => panel.state === 'done' || panel.state === 'skipped').length
        if (dashboardImport.phase === 'building') {
            return 'Building the dashboard'
        }
        if (dashboardImport.phase === 'checking_layout') {
            return `Checking layout · ${dashboardImport.layout_round} of ${dashboardImport.layout_rounds}`
        }
        if (dashboardImport.phase === 'matching') {
            if (!panels.length) {
                return 'Matching panels'
            }
            return dashboardImport.source === 'grafana'
                ? `Matching panels · ${settled} of ${panels.length}`
                : `Matching panels · ${settled} matched`
        }
        return 'Starting'
    }
    if (dashboardImport.status === 'failed' || !dashboardImport.summary) {
        return 'Failed'
    }
    const { total, imported, approximated } = dashboardImport.summary
    return `${imported + approximated} of ${total} panels imported`
}

function recentImportItem(
    dashboardImport: DashboardImportApi,
    openImport: (dashboardImport: DashboardImportApi) => void
): LemonMenuItem {
    return {
        label: (
            <div className="flex flex-col min-w-0 max-w-80">
                <span className="truncate">{dashboardImport.dashboard_name}</span>
                <span className="truncate text-xs text-secondary">{importStatusLine(dashboardImport)}</span>
            </div>
        ),
        icon:
            dashboardImport.status === 'running' ? (
                <Spinner />
            ) : dashboardImport.status === 'completed' ? (
                <IconCheckCircle className="text-success" />
            ) : (
                <IconWarning className="text-danger" />
            ),
        onClick: () => openImport(dashboardImport),
        'data-attr': 'metrics-dashboard-import-recent',
    }
}

export function MetricsDashboardActions(): JSX.Element {
    const { isLoading } = useValues(newDashboardLogic)
    const { addDashboard, setIsLoading } = useActions(newDashboardLogic)
    const { recentImports, runningImports } = useValues(metricsDashboardImportLogic)
    const { openImportModal, openImport } = useActions(metricsDashboardImportLogic)
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
                            items: [
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
                            ],
                        },
                        ...(recentImports.length
                            ? [
                                  {
                                      title: 'Recent imports',
                                      items: recentImports
                                          .slice(0, MAX_LISTED_IMPORTS)
                                          .map((dashboardImport) => recentImportItem(dashboardImport, openImport)),
                                  },
                              ]
                            : []),
                    ]}
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={runningImports.length ? <Spinner /> : undefined}
                        sideIcon={<IconChevronDown />}
                        disabledReason={importDisabledReason}
                        tooltip={
                            runningImports.length
                                ? `${runningImports.length} ${runningImports.length === 1 ? 'import is' : 'imports are'} running`
                                : undefined
                        }
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
