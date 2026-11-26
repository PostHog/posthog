import { LemonButton } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import type { SnapshotApi } from '../generated/api.schemas'
import { isRejectedByOther, personName } from '../lib/reviewDecisions'
import type { DecidingAction } from '../scenes/visualReviewRunSceneLogic'
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

// A dialog stays clickable during its close transition, so a double click would send the call twice.
function openConfirm(
    title: string,
    reason: string,
    description: string,
    confirmLabel: string,
    dataAttr: string,
    onConfirm: () => void
): void {
    let submitted = false
    LemonDialog.open({
        title,
        description: (
            <div className="flex flex-col gap-2">
                <blockquote className="m-0 border-l-2 border-danger pl-2 break-words">{reason}</blockquote>
                <p className="m-0">{description}</p>
            </div>
        ),
        primaryButton: {
            children: confirmLabel,
            onClick: () => {
                if (!submitted) {
                    submitted = true
                    onConfirm()
                }
            },
            'data-attr': dataAttr,
        },
        secondaryButton: { children: 'Cancel' },
    })
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
                            ? openConfirm(
                                  `Undo ${rejecter}'s rejection?`,
                                  reason,
                                  'Undoing it unblocks finalize, and the change needs review again.',
                                  'Undo rejection',
                                  'visual-review-snapshot-undo-reject-confirm',
                                  () => onUndo(true)
                              )
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
                            ? openConfirm(
                                  'Accept this change anyway?',
                                  reason,
                                  `This replaces ${rejecter}'s rejection.`,
                                  'Accept anyway',
                                  'visual-review-snapshot-accept-anyway-confirm',
                                  () => onAccept(true)
                              )
                            : onAccept(false)
                    }
                    loading={decidingAction === 'accept'}
                    disabledReason={disabledReason}
                    data-attr="visual-review-snapshot-accept-anyway"
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
