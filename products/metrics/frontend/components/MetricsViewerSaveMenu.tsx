import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { getMetricsInsightEditorDisabledReason } from '../metricsAccess'
import { metricsStarterDashboardLogic } from './metricsStarterDashboardLogic'
import { metricsViewerLogic } from './metricsViewerLogic'

export function MetricsViewerSaveMenu({
    noQueryReason,
    isHeatmap,
}: {
    noQueryReason: string | undefined
    /** Insight alerts only take a `MetricsQuery`, and the heatmap saves a histogram query. */
    isHeatmap: boolean
}): JSX.Element {
    const { savedInsightLoading } = useValues(metricsViewerLogic)
    const { saveAsInsight, addToDashboard, createAlert } = useActions(metricsViewerLogic)
    const { openModal: openStarterDashboardModal } = useActions(metricsStarterDashboardLogic)
    const insightEditorDisabledReason = getMetricsInsightEditorDisabledReason()

    return (
        <LemonMenu
            placement="bottom-end"
            items={[
                {
                    items: [
                        {
                            label: 'Add to dashboard',
                            onClick: () => addToDashboard(),
                            disabledReason: noQueryReason,
                            'data-attr': 'metrics-viewer-add-to-dashboard',
                        },
                        {
                            label: 'Save as insight',
                            onClick: () => saveAsInsight(),
                            disabledReason: noQueryReason,
                            'data-attr': 'metrics-viewer-save-as-insight',
                        },
                        {
                            label: 'Create alert',
                            onClick: () => createAlert(),
                            tooltip: 'Get notified when this metric crosses a threshold (uses insight alerts)',
                            disabledReason:
                                noQueryReason ??
                                (isHeatmap ? 'Alerts are not supported for the heatmap display' : undefined),
                            'data-attr': 'metrics-viewer-create-alert',
                        },
                    ],
                },
                {
                    items: [
                        {
                            label: 'New service dashboard',
                            onClick: openStarterDashboardModal,
                            tooltip: 'Create a dashboard with one insight per metric, charted as one line per series',
                            'data-attr': 'metrics-viewer-starter-dashboard',
                        },
                    ],
                },
            ]}
        >
            <LemonButton
                size="small"
                type="primary"
                sideIcon={<IconChevronDown />}
                loading={savedInsightLoading}
                disabledReason={insightEditorDisabledReason}
                data-attr="metrics-viewer-save-menu"
            >
                Save
            </LemonButton>
        </LemonMenu>
    )
}
