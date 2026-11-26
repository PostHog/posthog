import type { DecisionErrorApi, RunApi, RunProgressApi, SnapshotApi, UserBasicInfoApi } from '../generated/api.schemas'
import { decidesByPullRequest } from './runPredicates'

/** "1 change" or "3 changes", with the same plain digits as the other counts on the page. */
export function countChanges(count: number, adjective: string = ''): string {
    const noun = count === 1 ? 'change' : 'changes'
    return adjective ? `${count} ${adjective} ${noun}` : `${count} ${noun}`
}

export function shortSha(sha: string): string {
    return sha.slice(0, 7)
}

export function personName(user: UserBasicInfoApi | null | undefined): string {
    return user?.first_name || user?.email || 'Someone'
}

/** A rejection by someone other than the viewer, which only an explicit override replaces. */
export function isRejectedByOther(snapshot: SnapshotApi, currentUserId: number | null): boolean {
    const decision = snapshot.decision
    return decision?.state === 'rejected' && decision.by?.id !== currentUserId
}

/** The `seq` to send as `expected_seq`, so a decision someone made after this read is refused, not replaced. */
export function expectedSeq(snapshot: SnapshotApi): number {
    return snapshot.decision?.seq ?? 0
}

export type DecisionFilter = 'earlier' | 'rejected' | 'agent'

export function matchesDecisionFilter(snapshot: SnapshotApi, filter: DecisionFilter): boolean {
    const decision = snapshot.decision
    if (filter === 'rejected') {
        return snapshot.review_state === 'rejected'
    }
    if (decision?.state !== 'approved' || snapshot.review_state !== 'approved') {
        return false
    }
    return filter === 'earlier' ? decision.from_earlier_commit : decision.via === 'mcp'
}

export interface RejectionSummary {
    count: number
    /** Set when one person made every rejection. */
    rejecter: string | null
    /** Whether an agent made every rejection on that person's behalf. */
    byAgent: boolean
    /** Set when every rejection was made on the same commit. */
    commitSha: string | null
}

export function summarizeRejections(snapshots: SnapshotApi[]): RejectionSummary {
    const rejected = snapshots.filter((s) => s.review_state === 'rejected')
    const rejecters = new Set(rejected.map((s) => personName(s.decision?.by)))
    const commits = new Set(rejected.map((s) => s.decision?.commit_sha ?? ''))
    const [rejecter] = rejecters
    const [commitSha] = commits
    return {
        count: rejected.length,
        rejecter: rejecters.size === 1 ? rejecter : null,
        byAgent: rejected.length > 0 && rejected.every((s) => s.decision?.via === 'mcp'),
        commitSha: commits.size === 1 && commitSha ? commitSha : null,
    }
}

export interface FinalizeButtonCopy {
    label: string
    /** The progress shown next to the button. */
    note: string | null
    tooltip: string | null
    disabledReason: string | null
}

function progressNote(progress: RunProgressApi): string | null {
    const { approved, approved_on_earlier_commits, approved_via_mcp, rejected, needs_review } = progress
    const parts: string[] = []
    if (approved > 0) {
        if (approved_via_mcp > 0 && needs_review === 0 && rejected === 0) {
            parts.push(`${approved} accepted, ${approved_via_mcp} by an agent`)
        } else if (approved_on_earlier_commits > 0 && rejected === 0) {
            parts.push(`${approved} accepted (${approved_on_earlier_commits} on earlier commits)`)
        } else {
            parts.push(`${approved} accepted`)
        }
    }
    if (rejected > 0) {
        parts.push(`${rejected} rejected`)
    }
    if (needs_review > 0) {
        parts.push(`${needs_review} to review`)
    }
    return parts.length > 0 ? parts.join(', ') : null
}

export function rejectionBlocksFinalizeText(rejections: RejectionSummary, rejectedCount: number): string {
    if (rejections.rejecter && rejections.count === rejectedCount) {
        const person = rejections.rejecter
        const who = rejections.byAgent ? `An agent for ${person}` : person
        return rejectedCount === 1
            ? `${who} rejected 1 change. Finalize works once it has a new picture or ${person} undoes the rejection.`
            : `${who} rejected ${rejectedCount} changes. Finalize works once they have new pictures or ${person} undoes the rejections.`
    }
    return rejectedCount === 1
        ? '1 change is rejected. Finalize works once it has a new picture or the rejection is undone.'
        : `${rejectedCount} changes are rejected. Finalize works once they have new pictures or the rejections are undone.`
}

/** The finalize button of a ledger-mode head run, from the review progress of that run. */
export function finalizeButtonCopy(progress: RunProgressApi, rejections: RejectionSummary): FinalizeButtonCopy {
    const { approved, approved_via_mcp, rejected, needs_review } = progress
    const label = needs_review > 0 ? `Accept ${needs_review} and finalize` : 'Finalize run'
    const note = progressNote(progress)
    if (rejected > 0) {
        return { label, note, tooltip: null, disabledReason: rejectionBlocksFinalizeText(rejections, rejected) }
    }
    let tooltip: string
    if (needs_review > 0 && approved === 0) {
        tooltip = 'Accepts every change, removals included, and passes the gate.'
    } else if (needs_review > 0) {
        tooltip = `Accepts the ${countChanges(needs_review)} left and passes the gate.`
    } else if (approved_via_mcp > 0) {
        tooltip = `${countChanges(approved_via_mcp)} ${approved_via_mcp === 1 ? 'was' : 'were'} accepted by an agent. Finalizing passes the gate with them.`
    } else if (approved > 0) {
        tooltip = `Passes the gate with ${countChanges(approved, 'accepted')}.`
    } else {
        tooltip = 'Records the accepted pictures of quarantined stories.'
    }
    return { label, note, tooltip, disabledReason: null }
}

export type OlderRunSituation = 'head_processing' | 'head_ready' | 'head_finalized'

/** How the pull request's newest run stands, seen from an older run of it. Null on the newest run and outside ledger mode. */
export function olderRunSituation(run: RunApi | null): OlderRunSituation | null {
    const head = run?.head_run
    if (!run || !head || head.id === run.id || !decidesByPullRequest(run)) {
        return null
    }
    if (head.approved) {
        return 'head_finalized'
    }
    if (head.status === 'completed') {
        return 'head_ready'
    }
    if (head.status === 'pending' || head.status === 'processing') {
        return 'head_processing'
    }
    return null
}

/** Why decisions cannot change on this run, or null when they can. */
export function decisionsLockedReason(run: RunApi | null, pullRequestClosed: boolean): string | null {
    if (!run || !decidesByPullRequest(run)) {
        return null
    }
    if (pullRequestClosed) {
        return `PR #${run.pr_number} is merged or closed. This run is read only.`
    }
    if (run.approved) {
        return 'This run is finalized, so its decisions are fixed until the next push.'
    }
    if (run.head_run?.approved) {
        return `PR #${run.pr_number} was finalized on ${shortSha(run.head_run.commit_sha)}. Decisions on this pull request are fixed until the next push.`
    }
    return null
}

export function pictureKey(snapshot: SnapshotApi): string {
    return `${snapshot.baseline_artifact?.content_hash ?? ''}:${snapshot.current_artifact?.content_hash ?? ''}`
}

/** Whether a decision made on an older run counts on the newest run, by comparing the pictures both runs show. */
export function headPictureLine(snapshot: SnapshotApi, headPictureKeys: Record<string, string>): string {
    return headPictureKeys[snapshot.identifier] === pictureKey(snapshot)
        ? 'Same picture on the newest commit. Your decision counts there.'
        : 'Different picture on the newest commit. Your decision applies to this commit only.'
}

const DECISION_REFUSAL_MESSAGES: Record<string, string> = {
    decided_since: 'Someone decided on this change after you opened it. The page now shows the newest decision.',
    rejected_by_other: 'Someone rejected this change after you opened it. The page now shows the rejection.',
    run_finalized: 'This pull request was finalized, so its decisions are fixed until the next push.',
    pr_closed: 'This pull request is merged or closed, so its decisions can no longer change.',
    run_not_ready: 'This run is still processing. Decide once it completes.',
}

export interface DecisionErrorOutcome {
    code: string | null
    message: string
    /** A conflict means the page shows an outdated state, so it reloads. */
    refresh: boolean
}

interface DecisionCallError {
    status?: number
    code?: string | null
    detail?: string | null
    data?: Partial<DecisionErrorApi>
}

export function decisionErrorOutcome(error: unknown, fallback: string): DecisionErrorOutcome {
    const apiError = error as DecisionCallError | null
    const code = apiError?.data?.snapshots?.[0]?.code ?? apiError?.code ?? null
    const message = (code && DECISION_REFUSAL_MESSAGES[code]) || apiError?.detail || fallback
    return { code, message, refresh: apiError?.status === 409 }
}
