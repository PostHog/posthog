import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

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
                <LemonSelect
                    value={dashboardId}
                    onChange={selectDashboard}
                    loading={dashboardsLoading}
                    disabledReason={saving ? 'Saving results…' : undefined}
                    fullWidth
                    placeholder="Choose a dashboard"
                    options={nameSortedDashboards
                        .filter((dashboard) => !dashboard.deleted)
                        .map((dashboard) => ({
                            value: dashboard.id,
                            label: dashboard.name || 'Untitled',
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
