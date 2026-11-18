import { LemonButton } from '@posthog/lemon-ui'

import type { QuarantineLiftEntryApi } from '../generated/api.schemas'

interface QuarantineLiftOnMergeProps {
    prNumber: number
    isQuarantined: boolean
    /** The request to show for this identifier: its pending one, or else its newest. */
    liftRequest: QuarantineLiftEntryApi | null
    disabledReason: string | null
    isRequesting: boolean
    isCancelling: boolean
    onRequest: () => void
    onCancel: (requestId: string) => void
}

/** Lifts a quarantine once the pull request that fixes the story merges, and shows where that request stands. */
export function QuarantineLiftOnMerge({
    prNumber,
    isQuarantined,
    liftRequest,
    disabledReason,
    isRequesting,
    isCancelling,
    onRequest,
    onCancel,
}: QuarantineLiftOnMergeProps): JSX.Element | null {
    if (liftRequest?.state === 'applied') {
        return (
            <div className="text-xs" data-attr="visual-review-lift-on-merge-applied">
                <div className="font-semibold">Quarantine lifted</div>
                {liftRequest.lifted_at_sha && (
                    <div className="text-muted">
                        At <span className="font-mono">{liftRequest.lifted_at_sha.slice(0, 7)}</span>, after #{prNumber}{' '}
                        merged
                    </div>
                )}
            </div>
        )
    }
    if (!isQuarantined) {
        return null
    }
    if (liftRequest?.state === 'pending') {
        return (
            <div className="flex flex-col gap-1 text-xs" data-attr="visual-review-lift-on-merge-pending">
                <div className="font-semibold">Lifts when #{prNumber} merges</div>
                {liftRequest.detail && <div className="text-muted">{liftRequest.detail}</div>}
                <div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => onCancel(liftRequest.id)}
                        loading={isCancelling}
                        data-attr="visual-review-lift-on-merge-cancel"
                    >
                        Cancel lift
                    </LemonButton>
                </div>
            </div>
        )
    }
    return (
        <div>
            <LemonButton
                type="secondary"
                size="small"
                onClick={onRequest}
                loading={isRequesting}
                disabledReason={disabledReason ?? undefined}
                tooltip="The quarantine lifts after this pull request merges and the default branch renders this picture with a matching baseline. This does not approve the picture."
                data-attr="visual-review-lift-on-merge-request"
            >
                Lift quarantine when #{prNumber} merges
            </LemonButton>
        </div>
    )
}
