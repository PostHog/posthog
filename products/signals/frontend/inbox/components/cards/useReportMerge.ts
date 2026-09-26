import { useValues } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { signalsReportsMergeCreate } from 'products/signals/frontend/generated/api'

import { captureInboxReportAction, InboxReportActionSurface } from '../../inboxAnalytics'
import { MERGEABLE_REPORT_STATUSES } from '../../logics/mergeTargetPickerLogic'
import { SignalReport } from '../../types'
import { inboxReportDetailUrl } from '../../utils/inboxReportUrls'
import { displayConventionalCommitTitle } from '../../utils/reportPresentation'
import { openMergeReportDialog } from '../shell/MergeReportDialog'

// Mirrors `REASSIGN_SIGNAL_ROW_CAP` in products/signals/backend/signal_metadata.py. The API refuses
// a source with more signals than this with a 409, because the signal move reads one bounded page.
// The cap applies only to the source, so the survivor picker does not use it.
const MERGE_SOURCE_SIGNAL_CAP = 5000

/**
 * Shared "Merge into…" handler for the context menu and the detail pane, mirroring
 * `useReportRefund`. Opens the merge dialog and posts to the survivor's merge endpoint with this
 * report as the only source. The server moves the signals and the work log, and archives this
 * report. `canMerge` is only a display gate: the server enforces the same status and size rules.
 */
export function useReportMerge({
    report,
    surface,
    onMerged,
}: {
    report: SignalReport
    /** Which surface the merge was triggered from, for the `merge` analytics. */
    surface: InboxReportActionSurface
    /** Fired once the merge API call succeeds, with the id of the report that stays. */
    onMerged?: (survivorId: string) => void
}): { canMerge: boolean; onMergeClick: (event?: React.MouseEvent) => void } {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeamId } = useValues(teamLogic)

    const canMerge =
        !!featureFlags[FEATURE_FLAGS.SIGNALS_REPORT_MERGE] &&
        MERGEABLE_REPORT_STATUSES.includes(report.status) &&
        report.signal_count <= MERGE_SOURCE_SIGNAL_CAP

    const onMergeClick = (event?: React.MouseEvent): void => {
        event?.preventDefault()
        event?.stopPropagation()
        openMergeReportDialog({
            reportId: report.id,
            reportTitle: displayConventionalCommitTitle(report.title, 'Untitled report'),
            onConfirm: async ({ survivor, reason }) => {
                try {
                    if (currentTeamId == null) {
                        throw new Error('No current project')
                    }
                    await signalsReportsMergeCreate(String(currentTeamId), survivor.id, {
                        source_report_ids: [report.id],
                        ...(reason ? { reason } : {}),
                    })
                } catch (error: any) {
                    lemonToast.error(error?.detail || error?.message || 'Failed to merge this report')
                    throw error // keep the dialog open so the user can pick another report or retry
                }
                // The reason is free text that can name a customer's own entities, so only its presence is captured.
                captureInboxReportAction({
                    report,
                    actionType: 'merge',
                    surface,
                    extra: { merge_survivor_report_id: survivor.id, has_merge_reason: !!reason },
                })
                lemonToast.success(`Merged into "${survivor.title}"`, {
                    button: {
                        label: 'Open report',
                        action: () => router.actions.push(inboxReportDetailUrl(survivor.id)),
                    },
                })
                onMerged?.(survivor.id)
            },
        })
    }

    return { canMerge, onMergeClick }
}
