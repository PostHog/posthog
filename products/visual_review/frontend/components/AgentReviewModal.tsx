import { useActions, useValues } from 'kea'

import { IconAIText, IconCheckCircle, IconClock, IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { AgentVerdictApi, RunAgentReviewApi, SnapshotApi } from '../generated/api.schemas'
import { visualReviewRunSceneLogic } from '../scenes/visualReviewRunSceneLogic'

type Verdict = 'approved' | 'rejected' | 'deferred'

interface VerdictPresentation {
    label: string
    tagType: 'success' | 'danger' | 'warning'
    icon: JSX.Element
    description: string
}

const VERDICT_PRESENTATION: Record<Verdict, VerdictPresentation> = {
    approved: {
        label: 'Approve',
        tagType: 'success',
        icon: <IconCheckCircle />,
        description: 'Looks intentional — safe to accept.',
    },
    rejected: {
        label: 'Keep unapproved',
        tagType: 'danger',
        icon: <IconWarning />,
        description: "Looks like noise or a regression — don't approve.",
    },
    deferred: {
        label: 'Needs a human',
        tagType: 'warning',
        icon: <IconClock />,
        description: "Agent can't tell from the metrics alone.",
    },
}

function presentationFor(verdict: string): VerdictPresentation {
    return VERDICT_PRESENTATION[verdict as Verdict] ?? VERDICT_PRESENTATION.deferred
}

function ConfidenceBar({ confidence }: { confidence: number }): JSX.Element {
    const pct = Math.round(confidence * 100)
    // Saturate above 80 to soft-green, dim below 50 to muted — gives the
    // viewer an at-a-glance sense of how much weight to put on the verdict.
    const barColor = confidence >= 0.8 ? 'bg-success' : confidence >= 0.5 ? 'bg-primary' : 'bg-muted'
    return (
        <div className="flex items-center gap-2">
            <div className="w-24 h-1.5 bg-bg-3000 rounded overflow-hidden">
                <div
                    className={`h-full ${barColor} transition-all`}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: `${pct}%` }}
                />
            </div>
            <span className="text-xs text-muted tabular-nums">{pct}% confidence</span>
        </div>
    )
}

function SnapshotRow({
    snapshot,
    verdict,
    isSelected,
    onSelect,
}: {
    snapshot: SnapshotApi
    verdict: AgentVerdictApi
    isSelected: boolean
    onSelect: () => void
}): JSX.Element {
    const presentation = presentationFor(verdict.verdict)
    return (
        <button
            type="button"
            onClick={onSelect}
            className={`w-full text-left flex items-start gap-3 p-3 rounded border transition-colors ${
                isSelected
                    ? 'border-primary bg-primary-highlight'
                    : 'border-border hover:border-primary hover:bg-bg-3000'
            }`}
            data-attr="visual-review-agent-review-snapshot-row"
        >
            <div className="shrink-0 mt-0.5">
                <LemonTag type={presentation.tagType} size="small" icon={presentation.icon}>
                    {presentation.label}
                </LemonTag>
            </div>
            <div className="flex-1 min-w-0">
                <div className="font-mono text-xs truncate" title={snapshot.identifier}>
                    {snapshot.identifier}
                </div>
                <div className="text-xs text-muted mt-1">{verdict.reasoning}</div>
            </div>
            <div className="shrink-0">
                <Tooltip title={`Agent confidence: ${Math.round(verdict.confidence * 100)}%`}>
                    <span className="text-xs text-muted tabular-nums">{Math.round(verdict.confidence * 100)}%</span>
                </Tooltip>
            </div>
        </button>
    )
}

function VerdictHeader({ review }: { review: RunAgentReviewApi }): JSX.Element {
    const presentation = presentationFor(review.verdict)
    return (
        <div className="flex flex-col gap-3 p-4 border border-border rounded bg-bg-light">
            <div className="flex items-center gap-3 flex-wrap">
                <LemonTag type={presentation.tagType} size="medium" icon={presentation.icon}>
                    {presentation.label}
                </LemonTag>
                <ConfidenceBar confidence={review.confidence} />
                <span className="text-xs text-muted ml-auto">
                    by <span className="font-mono">{review.agent}</span> · {dayjs(review.generated_at).fromNow()}
                </span>
            </div>
            <p className="text-sm m-0">{review.summary}</p>
            <p className="text-xs text-muted m-0 italic">
                Advisory only — the system will never act on this without you.
            </p>
        </div>
    )
}

export function AgentReviewModal(): JSX.Element | null {
    const { run, snapshots, isAgentReviewModalOpen, isRequestingAgentReview, selectedSnapshotId } =
        useValues(visualReviewRunSceneLogic)
    const { setAgentReviewModalOpen, requestAgentReview, setSelectedSnapshotId } = useActions(visualReviewRunSceneLogic)

    if (!run) {
        return null
    }

    const review = run.agent_review ?? null
    const reviewedSnapshots = snapshots.filter((s: SnapshotApi) => s.agent_review != null)

    return (
        <LemonModal
            isOpen={isAgentReviewModalOpen}
            onClose={() => setAgentReviewModalOpen(false)}
            title={
                <span className="flex items-center gap-2">
                    <IconAIText className="text-primary" />
                    Agent review
                </span>
            }
            description="The agent reviewed every changed snapshot in this run and gave each one a verdict. Use it as a second opinion — you still own the final call."
            width={720}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={() => setAgentReviewModalOpen(false)}
                        data-attr="visual-review-agent-review-modal-close"
                    >
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={requestAgentReview}
                        loading={isRequestingAgentReview}
                        icon={<IconAIText />}
                        data-attr="visual-review-agent-review-modal-rerun"
                    >
                        Re-run review
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                {review ? <VerdictHeader review={review} /> : null}
                {reviewedSnapshots.length > 0 ? (
                    <div className="space-y-2">
                        <h4 className="text-sm font-semibold m-0">Per-snapshot verdicts</h4>
                        <div className="space-y-1.5 max-h-[420px] overflow-y-auto">
                            {reviewedSnapshots.map((snapshot: SnapshotApi) =>
                                snapshot.agent_review ? (
                                    <SnapshotRow
                                        key={snapshot.id}
                                        snapshot={snapshot}
                                        verdict={snapshot.agent_review}
                                        isSelected={selectedSnapshotId === snapshot.id}
                                        onSelect={() => setSelectedSnapshotId(snapshot.id)}
                                    />
                                ) : null
                            )}
                        </div>
                    </div>
                ) : (
                    <p className="text-sm text-muted m-0">No snapshots needed agent review.</p>
                )}
            </div>
        </LemonModal>
    )
}
