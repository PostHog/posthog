import { useActions, useValues } from 'kea'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

import type { DashboardWidgetComponentProps } from 'products/dashboards/frontend/widgets/registry'

import { NotebookWidgetTrustControls } from '../NotebookNodeGeneratedWidget/NotebookWidgetTrustControls'
import { notebookDashboardWidgetLogic } from './notebookDashboardWidgetLogic'
import { NOTEBOOK_WIDGET_NO_SNAPSHOT_REASON, openRefreshFromNotebookDialog } from './openRefreshFromNotebookDialog'

export function NotebookDashboardWidgetMenu({
    tileId,
    config,
    onConfigPublished,
}: DashboardWidgetComponentProps): JSX.Element {
    const notebookShortId = config.notebookShortId as string
    const logic = notebookDashboardWidgetLogic({
        tileId,
        notebookShortId,
        snapshotId: config.snapshotId as string,
        onSnapshotPublished: onConfigPublished,
    })
    const { snapshot, refreshing, runId, stopping, sourceLoading } = useValues(logic)
    const { refresh, stopRun, setSourceOpen } = useActions(logic)

    return (
        <>
            <LemonButton fullWidth to={urls.notebook(notebookShortId)}>
                Open notebook
            </LemonButton>
            {onConfigPublished ? (
                <LemonButton
                    fullWidth
                    loading={refreshing}
                    disabledReason={!snapshot ? NOTEBOOK_WIDGET_NO_SNAPSHOT_REASON : undefined}
                    onClick={() => openRefreshFromNotebookDialog(refresh)}
                >
                    Refresh from notebook
                </LemonButton>
            ) : null}
            {runId ? (
                <LemonButton fullWidth loading={stopping} onClick={stopRun}>
                    Stop
                </LemonButton>
            ) : null}
            <LemonButton
                fullWidth
                loading={sourceLoading}
                disabledReason={!snapshot ? NOTEBOOK_WIDGET_NO_SNAPSHOT_REASON : undefined}
                onClick={() => setSourceOpen(true)}
                data-attr="notebook-widget-view-source"
            >
                View source
            </LemonButton>
            {snapshot ? (
                <div className="flex flex-col gap-2 px-2 py-1.5">
                    <span className="text-xs text-secondary">
                        Saved {humanFriendlyDetailedTime(snapshot.created_at)}
                    </span>
                    <NotebookWidgetTrustControls
                        variant="menu"
                        buildHash={snapshot.build_hash}
                        securityReview={snapshot.security_review}
                        isEditable={false}
                        onRun={() => {}}
                        onViewSource={() => setSourceOpen(true)}
                    />
                </div>
            ) : null}
            <LemonDivider />
        </>
    )
}
