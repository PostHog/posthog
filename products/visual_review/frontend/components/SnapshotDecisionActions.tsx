import { LemonButton } from '@posthog/lemon-ui'

import type { SnapshotApi } from '../generated/api.schemas'
import { isRejectedByOther, personName } from '../lib/reviewDecisions'
import type { DecidingAction } from '../scenes/visualReviewRunSceneLogic'
import { openOverrideRejectionDialog } from './openOverrideRejectionDialog'
import { openRejectChangeDialog } from './openRejectChangeDialog'

export interface SnapshotDecisionActionsProps {
    snapshot: SnapshotApi
    currentUserId: number | null
    isQuarantined: boolean
    /** Set when decisions on this pull request cannot change, which disables every button with this text. */
    lockedReason: string | null
    decidingAction: DecidingAction | null
    onAccept: (overrideRejection: boolean) => void
    onReject: (reason: string) => void
    onUndo: (overrideRejection: boolean) => void
    onTolerate: () => void
}

/** Accept, reject and undo on a story of a ledger-mode pull request run, where decisions count across its runs. */
export function SnapshotDecisionActions({
    snapshot,
    currentUserId,
    isQuarantined,
    lockedReason,
    decidingAction,
    onAccept,
    onReject,
    onUndo,
    onTolerate,
}: SnapshotDecisionActionsProps): JSX.Element | null {
    const isRemoved = snapshot.result === 'removed'
    const busyReason = decidingAction ? 'Saving the decision' : undefined
    const disabledReason = lockedReason ?? busyReason

    if (snapshot.review_state === 'approved') {
        return (
            <LemonButton
                type="secondary"
                size="small"
                onClick={() => onUndo(false)}
                loading={decidingAction === 'clear'}
                disabledReason={disabledReason}
                data-attr="visual-review-snapshot-undo-accept"
            >
                Undo accept
            </LemonButton>
        )
    }

    if (snapshot.review_state === 'rejected') {
        const byOther = isRejectedByOther(snapshot, currentUserId)
        const rejecter = personName(snapshot.decision?.by)
        const reason = snapshot.decision?.reason ?? ''
        return (
            <>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() =>
                        byOther
                            ? openOverrideRejectionDialog({
                                  title: `Undo ${rejecter}'s rejection?`,
                                  reason,
                                  description: 'Undoing it unblocks finalize, and the change needs review again.',
                                  confirmLabel: 'Undo rejection',
                                  dataAttr: 'visual-review-snapshot-undo-reject-confirm',
                                  onConfirm: () => onUndo(true),
                              })
                            : onUndo(false)
                    }
                    loading={decidingAction === 'clear'}
                    disabledReason={disabledReason}
                    data-attr="visual-review-snapshot-undo-reject"
                >
                    Undo reject
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() =>
                        byOther
                            ? openOverrideRejectionDialog({
                                  title: 'Accept this change anyway?',
                                  reason,
                                  description: `This replaces ${rejecter}'s rejection.`,
                                  confirmLabel: 'Accept anyway',
                                  dataAttr: 'visual-review-snapshot-accept-anyway-confirm',
                                  onConfirm: () => onAccept(true),
                              })
                            : onAccept(false)
                    }
                    loading={decidingAction === 'accept'}
                    disabledReason={disabledReason}
                    data-attr={byOther ? 'visual-review-snapshot-accept-anyway' : 'visual-review-snapshot-accept'}
                >
                    {byOther ? 'Accept anyway' : 'Accept change'}
                </LemonButton>
            </>
        )
    }

    // Quarantined stories keep their own accept button, and a tolerated story needs nothing.
    if (snapshot.review_state !== 'pending' || isQuarantined) {
        return null
    }

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                onClick={() => openRejectChangeDialog(onReject)}
                loading={decidingAction === 'reject'}
                disabledReason={disabledReason}
                data-attr="visual-review-snapshot-reject"
            >
                Reject
            </LemonButton>
            {snapshot.result === 'changed' && (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onTolerate}
                    disabledReason={disabledReason}
                    data-attr="visual-review-snapshot-tolerate"
                >
                    Tolerate
                </LemonButton>
            )}
            <LemonButton
                type="primary"
                size="small"
                onClick={() => onAccept(false)}
                loading={decidingAction === 'accept'}
                disabledReason={disabledReason}
                tooltip={isRemoved ? 'Removes this story from the baseline when the PR merges.' : undefined}
                data-attr="visual-review-snapshot-accept"
            >
                {isRemoved ? 'Accept removal' : 'Accept change'}
            </LemonButton>
        </>
    )
}
