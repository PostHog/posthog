import type { SnapshotApi } from '../generated/api.schemas'
import { CurrentSnapshotDecision } from './CurrentSnapshotDecision'
import { EarlierSnapshotDecision } from './EarlierSnapshotDecision'

/** Who decided on the pictures this story shows, and whether a decision here counts on the newest run. */
export function SnapshotDecisionLine({
    snapshot,
    headPictureLine,
}: {
    snapshot: SnapshotApi
    headPictureLine: string | null
}): JSX.Element | null {
    const { decision, earlier_decision } = snapshot
    if (!decision && !earlier_decision && !headPictureLine) {
        return null
    }
    return (
        <div
            className="flex flex-col gap-1 mb-4 text-sm text-secondary break-words"
            data-attr="visual-review-decision-line"
        >
            {decision ? (
                <CurrentSnapshotDecision decision={decision} />
            ) : earlier_decision ? (
                <EarlierSnapshotDecision decision={earlier_decision} />
            ) : null}
            {headPictureLine && <span>{headPictureLine}</span>}
        </div>
    )
}
