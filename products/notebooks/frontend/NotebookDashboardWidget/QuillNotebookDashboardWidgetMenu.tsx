import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonDialog } from '@posthog/lemon-ui'
import { Badge, DropdownMenuItem, DropdownMenuSeparator } from '@posthog/quill'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

import type { DashboardWidgetComponentProps } from 'products/dashboards/frontend/widgets/registry'

import type { WidgetSecurityReviewApi } from '../generated/api.schemas'
import { SEVERITY_LABELS } from '../NotebookNodeGeneratedWidget/NotebookWidgetTrustControls'
import { notebookDashboardWidgetLogic } from './notebookDashboardWidgetLogic'

function reviewBadgeVariant(severity: WidgetSecurityReviewApi['severity']): 'success' | 'warning' | 'destructive' {
    if (severity === 'none') {
        return 'success'
    }
    return severity === 'high' || severity === 'critical' ? 'destructive' : 'warning'
}

export function QuillNotebookDashboardWidgetMenu({
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
    const noSnapshotReason = !snapshot ? 'Load the saved results first' : undefined

    return (
        <>
            <DropdownMenuItem onClick={() => router.actions.push(urls.notebook(notebookShortId))}>
                Open notebook
            </DropdownMenuItem>
            {onConfigPublished ? (
                <DropdownMenuItem
                    disabledReason={refreshing ? 'Refreshing…' : noSnapshotReason}
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
                </DropdownMenuItem>
            ) : null}
            {runId ? (
                <DropdownMenuItem disabledReason={stopping ? 'Stopping…' : undefined} onClick={stopRun}>
                    Stop
                </DropdownMenuItem>
            ) : null}
            <DropdownMenuItem
                disabledReason={sourceLoading ? 'Loading…' : noSnapshotReason}
                onClick={() => setSourceOpen(true)}
                data-attr="notebook-widget-view-source"
            >
                View source
            </DropdownMenuItem>
            {snapshot ? (
                <div className="flex flex-col items-start gap-1.5 px-2 py-1.5 text-xs text-secondary">
                    <span>Saved {humanFriendlyDetailedTime(snapshot.created_at)}</span>
                    {snapshot.security_review ? (
                        <Badge variant={reviewBadgeVariant(snapshot.security_review.severity)}>
                            Automated review: {SEVERITY_LABELS[snapshot.security_review.severity]}
                        </Badge>
                    ) : (
                        <Badge>Automated review unavailable</Badge>
                    )}
                    {snapshot.build_hash ? (
                        <span className="font-mono">Build {snapshot.build_hash.slice(0, 12)}</span>
                    ) : null}
                </div>
            ) : null}
            <DropdownMenuSeparator />
        </>
    )
}
