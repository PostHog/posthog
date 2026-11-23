import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { Badge, DropdownMenuItem, DropdownMenuSeparator } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { DashboardWidgetComponentProps } from 'products/dashboards/frontend/widgets/registry'

import type { WidgetSecurityReviewApi } from '../generated/api.schemas'
import { SEVERITY_LABELS } from '../NotebookNodeGeneratedWidget/NotebookWidgetTrustControls'
import { notebookDashboardWidgetLogic } from './notebookDashboardWidgetLogic'
import { NOTEBOOK_WIDGET_NO_SNAPSHOT_REASON, openRefreshFromNotebookDialog } from './openRefreshFromNotebookDialog'

function reviewBadgeVariant(review: WidgetSecurityReviewApi | null): 'default' | 'success' | 'warning' | 'destructive' {
    if (!review) {
        return 'default'
    }
    if (review.severity === 'none') {
        return 'success'
    }
    return review.severity === 'high' || review.severity === 'critical' ? 'destructive' : 'warning'
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
    const noSnapshotReason = snapshot ? undefined : NOTEBOOK_WIDGET_NO_SNAPSHOT_REASON

    return (
        <>
            <DropdownMenuItem onClick={() => router.actions.push(urls.notebook(notebookShortId))}>
                Open notebook
            </DropdownMenuItem>
            {onConfigPublished ? (
                <DropdownMenuItem
                    disabledReason={refreshing ? 'Refreshing…' : noSnapshotReason}
                    onClick={() => openRefreshFromNotebookDialog(refresh)}
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
                disabledReason={sourceLoading ? 'Loading source…' : noSnapshotReason}
                onClick={() => setSourceOpen(true)}
                description={
                    snapshot ? (
                        <>
                            <span>Saved </span>
                            <TZLabel time={snapshot.created_at} noStyles />
                            {snapshot.build_hash ? (
                                <span translate="no"> · Build {snapshot.build_hash.slice(0, 12)}</span>
                            ) : null}
                        </>
                    ) : undefined
                }
                data-attr="notebook-widget-view-source"
            >
                View source
                {snapshot ? (
                    <Badge variant={reviewBadgeVariant(snapshot.security_review)} className="ml-auto">
                        {snapshot.security_review
                            ? `Automated review: ${SEVERITY_LABELS[snapshot.security_review.severity]}`
                            : 'Automated review unavailable'}
                    </Badge>
                ) : null}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
        </>
    )
}
