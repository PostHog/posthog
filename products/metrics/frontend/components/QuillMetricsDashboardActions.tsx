import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconChevronDown, IconWarning } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Spinner,
} from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { metricsDashboardImportLogic } from '../dashboardImport/metricsDashboardImportLogic'
import { QuillSuggestedDashboardsMenu } from '../suggestedDashboards/QuillSuggestedDashboardsMenu'
import { importStatusLine, MAX_LISTED_IMPORTS } from './MetricsDashboardActions'

export function QuillMetricsDashboardActions(): JSX.Element | null {
    const { recentImports, runningImports } = useValues(metricsDashboardImportLogic)
    const { openImportModal, openImport } = useActions(metricsDashboardImportLogic)
    const importEnabled = useFeatureFlag('METRICS_DASHBOARD_IMPORT')
    const suggestionsEnabled = useFeatureFlag('METRICS_SUGGESTED_DASHBOARDS')

    if (!importEnabled && !suggestionsEnabled) {
        return null
    }
    const importDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Dashboard, AccessControlLevel.Editor) ??
        getAccessControlDisabledReason(AccessControlResourceType.Insight, AccessControlLevel.Editor)

    return (
        <div className="flex flex-wrap items-center gap-2">
            {suggestionsEnabled && <QuillSuggestedDashboardsMenu />}
            {importEnabled && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="outline"
                                disabledReason={importDisabledReason}
                                tooltip={
                                    runningImports.length
                                        ? `${runningImports.length} ${runningImports.length === 1 ? 'import is' : 'imports are'} running`
                                        : undefined
                                }
                                data-attr="metrics-dashboard-import-menu"
                            />
                        }
                    >
                        {runningImports.length ? <Spinner /> : null}
                        Import
                        <IconChevronDown />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="min-w-56">
                        <DropdownMenuGroup>
                            <DropdownMenuItem
                                onClick={() => openImportModal('grafana')}
                                data-attr="metrics-dashboard-import-grafana"
                            >
                                Import from Grafana
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                onClick={() => openImportModal('screenshot')}
                                data-attr="metrics-dashboard-import-screenshot"
                            >
                                Import from screenshot
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                        {recentImports.length > 0 && (
                            <>
                                <DropdownMenuSeparator />
                                <DropdownMenuGroup>
                                    <DropdownMenuLabel>Recent imports</DropdownMenuLabel>
                                    {recentImports.slice(0, MAX_LISTED_IMPORTS).map((dashboardImport, index) => (
                                        <DropdownMenuItem
                                            key={dashboardImport.id ?? index}
                                            onClick={() => openImport(dashboardImport)}
                                            data-attr="metrics-dashboard-import-recent"
                                            description={importStatusLine(dashboardImport)}
                                        >
                                            {dashboardImport.status === 'running' ? (
                                                <Spinner />
                                            ) : dashboardImport.status === 'completed' ? (
                                                <IconCheckCircle className="text-success" />
                                            ) : (
                                                <IconWarning className="text-danger" />
                                            )}
                                            <span className="truncate max-w-80">{dashboardImport.dashboard_name}</span>
                                        </DropdownMenuItem>
                                    ))}
                                </DropdownMenuGroup>
                            </>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </div>
    )
}
