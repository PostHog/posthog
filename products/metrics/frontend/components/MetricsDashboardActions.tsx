import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconChevronDown, IconWarning } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItem, Spinner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { DashboardImportApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsDashboardImportLogic } from '../dashboardImport/metricsDashboardImportLogic'

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

export function MetricsDashboardActions(): JSX.Element | null {
    const { recentImports, runningImports } = useValues(metricsDashboardImportLogic)
    const { openImportModal, openImport } = useActions(metricsDashboardImportLogic)
    const importEnabled = useFeatureFlag('METRICS_DASHBOARD_IMPORT')

    if (!importEnabled) {
        return null
    }
    const importDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Dashboard, AccessControlLevel.Editor) ??
        getAccessControlDisabledReason(AccessControlResourceType.Insight, AccessControlLevel.Editor)

    return (
        <div className="flex flex-wrap items-center gap-2">
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
        </div>
    )
}
