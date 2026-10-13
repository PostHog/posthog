import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonDivider } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

import type { DashboardWidgetComponentProps } from 'products/dashboards/frontend/widgets/registry'

import { NotebookWidgetTrustControls } from '../NotebookNodeGeneratedWidget/NotebookWidgetTrustControls'
import { notebookDashboardWidgetLogic } from './notebookDashboardWidgetLogic'

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
                    disabledReason={!snapshot ? 'Load the saved results first' : undefined}
                    onClick={() =>
                        LemonDialog.open({
                            title: 'Refresh from notebook?',
                            description:
                                'This runs all saved data cells using the notebook’s variables. Python compute may incur charges. Dashboard filters do not change these results.',
                            primaryButton: { children: 'Run notebook', onClick: refresh },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }
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
                disabledReason={!snapshot ? 'Load the saved results first' : undefined}
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
