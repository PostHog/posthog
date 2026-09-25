import { useActions, useValues } from 'kea'

import { IconPinFilled } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonSearchableSelect, Tooltip } from '@posthog/lemon-ui'

import { dashboardsModel } from '~/models/dashboardsModel'
import { AccessControlLevel } from '~/types'

import { NotebookWidgetDashboardProps, notebookWidgetDashboardLogic } from './notebookWidgetDashboardLogic'

export function NotebookWidgetDashboardModal(props: NotebookWidgetDashboardProps): JSX.Element {
    const { isOpen, saving, error, dashboardId } = useValues(notebookWidgetDashboardLogic(props))
    const { close, addToDashboard, selectDashboard } = useActions(notebookWidgetDashboardLogic(props))
    const { nameSortedDashboards, dashboardsLoading } = useValues(dashboardsModel)
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={saving ? undefined : close}
            title="Add widget to dashboard"
            width={480}
            footer={
                <>
                    <LemonButton onClick={close} disabledReason={saving ? 'Saving results…' : undefined}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={addToDashboard}
                        loading={saving}
                        disabledReason={!dashboardId ? 'Choose a dashboard' : undefined}
                        data-attr="notebook-widget-add-to-dashboard"
                    >
                        Add to dashboard
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <p className="mb-0">
                    Save this widget and its current dataframe results on a dashboard. Opening the dashboard will not
                    run notebook code.
                </p>
                <LemonSearchableSelect
                    value={dashboardId}
                    onChange={selectDashboard}
                    loading={dashboardsLoading}
                    disabledReason={saving ? 'Saving results…' : undefined}
                    fullWidth
                    placeholder="Choose a dashboard"
                    searchPlaceholder="Search by name, description, or creator"
                    searchKeys={['label', 'description', 'creator']}
                    searchInputDataAttr="notebook-widget-dashboard-search"
                    noResultsMessage="No dashboards match your search"
                    data-attr="notebook-widget-dashboard-select"
                    options={nameSortedDashboards
                        .filter((dashboard) => !dashboard.deleted)
                        .map((dashboard) => ({
                            value: dashboard.id,
                            label: dashboard.name || 'Untitled',
                            description: dashboard.description,
                            creator: dashboard.created_by
                                ? `${dashboard.created_by.first_name} ${dashboard.created_by.email}`
                                : '',
                            labelInMenu: (
                                <span className="flex min-w-0 flex-1 flex-col gap-1 text-left">
                                    <span className="flex min-w-0 items-center gap-2">
                                        <span className="truncate">{dashboard.name || 'Untitled'}</span>
                                        {dashboard.pinned && (
                                            <Tooltip title="Pinned dashboard">
                                                <span className="flex shrink-0">
                                                    <IconPinFilled className="text-secondary" />
                                                </span>
                                            </Tooltip>
                                        )}
                                    </span>
                                    {dashboard.description && (
                                        <span className="line-clamp-2 text-xs font-normal text-secondary">
                                            {dashboard.description}
                                        </span>
                                    )}
                                    <span className="truncate text-xs font-normal text-secondary">
                                        {dashboard.created_by
                                            ? `Created by ${dashboard.created_by.first_name || dashboard.created_by.email}`
                                            : 'Creator unavailable'}
                                    </span>
                                </span>
                            ),
                            disabledReason:
                                dashboard.user_access_level === AccessControlLevel.Viewer
                                    ? 'You need edit access to this dashboard'
                                    : undefined,
                        }))}
                />
                <span className="text-secondary text-sm">
                    Use Refresh from notebook on the dashboard to update the data. Notebook variables control the
                    results.
                </span>
                {error ? <LemonBanner type="error">{error}</LemonBanner> : null}
            </div>
        </LemonModal>
    )
}
