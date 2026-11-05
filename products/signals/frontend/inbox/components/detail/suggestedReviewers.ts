import type { ReviewerEditActionEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { captureInboxReportAction, InboxReportActionSurface } from '../../inboxAnalytics'
import { EnrichedReviewer, ReviewerRemoval, SignalReport } from '../../types'
import { reviewerRemovalReasonOptions } from '../../utils/reviewerRemovalReasons'
import { AvailableReviewerOption, reviewerMatchesOption, reviewersToWriteContent } from './reviewerDisplay'

export interface ReviewerClaim {
    claimantUuid: string | null
    currentUserUuid: string | null
    claimable: boolean
    saving: boolean
    onSetClaimed: (claimed: boolean) => void
}

export function isReviewerClaimant(reviewer: EnrichedReviewer, claim: ReviewerClaim): boolean {
    return !!reviewer.user && reviewer.user.uuid === claim.claimantUuid
}

export function reviewerClaimRemoveDisabledReason(
    reviewer: EnrichedReviewer,
    claim: ReviewerClaim | undefined,
    displayName: string
): string | undefined {
    if (!claim) {
        return undefined
    }
    if (!isReviewerClaimant(reviewer, claim)) {
        // A pending claim makes this row the claimant row, so the remove must wait for it.
        return claim.saving && !!reviewer.user && reviewer.user.uuid === claim.currentUserUuid ? 'Updating…' : undefined
    }
    return reviewer.user?.uuid === claim.currentUserUuid
        ? "You're working on this report. Unclaim it before you remove yourself."
        : `${displayName} is working on this report.`
}

const OTHER_SOURCE_LABELS = new Set(['Code history', 'Added by teammate', 'Agent suggestion'])

export const MAX_VISIBLE_SUGGESTIONS = 5

export function getReviewerSourceLabel(reviewer: EnrichedReviewer): string {
    if (reviewer.source_label) {
        return reviewer.source_label
    }
    if (reviewer.relevant_commits.length > 0) {
        return 'Code history'
    }
    if (reviewer.reason?.startsWith('Added as a reviewer by ')) {
        return 'Added by teammate'
    }
    return 'Agent suggestion'
}

export function isScoutReviewer(reviewer: EnrichedReviewer): boolean {
    if (reviewer.source_skill !== undefined) {
        return Boolean(reviewer.source_skill && reviewer.relevant_commits.length === 0)
    }
    return !OTHER_SOURCE_LABELS.has(getReviewerSourceLabel(reviewer))
}

export function getReviewerExplanation(reviewer: EnrichedReviewer): string | null {
    if ('explanation' in reviewer) {
        return reviewer.explanation ?? null
    }
    return reviewer.reason ?? reviewer.relevant_commits[0]?.reason ?? null
}

interface ReviewerPersonItem {
    kind: 'person'
    key: string
    reviewer: EnrichedReviewer
}

interface ReviewerReasonGroupItem {
    kind: 'reason-group'
    key: string
    reason: string
    reviewers: EnrichedReviewer[]
}

type ReviewerItem = ReviewerPersonItem | ReviewerReasonGroupItem

function reviewerKey(reviewer: EnrichedReviewer): string {
    return reviewer.user?.uuid ?? reviewer.user_uuid ?? reviewer.github_login ?? getReviewerDisplayFallback(reviewer)
}

function getReviewerDisplayFallback(reviewer: EnrichedReviewer): string {
    return reviewer.github_name ?? reviewer.user?.email ?? 'unknown-reviewer'
}

function reviewerReasonGroupKey(reviewer: EnrichedReviewer, reason: string): string {
    const isScout = isScoutReviewer(reviewer)
    return JSON.stringify([
        'reason-group',
        reason,
        isScout ? 'scout' : 'other',
        isScout ? null : getReviewerSourceLabel(reviewer),
    ])
}

export function buildReviewerItems(reviewers: EnrichedReviewer[]): ReviewerItem[] {
    const items: ReviewerItem[] = []
    const reasonGroups = new Map<string, ReviewerReasonGroupItem>()

    for (const reviewer of reviewers) {
        const reason = getReviewerExplanation(reviewer)
        if (!reason) {
            items.push({ kind: 'person', key: reviewerKey(reviewer), reviewer })
            continue
        }

        const groupKey = reviewerReasonGroupKey(reviewer, reason)
        const existing = reasonGroups.get(groupKey)
        if (existing) {
            existing.reviewers.push(reviewer)
        } else {
            const item: ReviewerReasonGroupItem = {
                kind: 'reason-group',
                key: groupKey,
                reason,
                reviewers: [reviewer],
            }
            reasonGroups.set(groupKey, item)
            items.push(item)
        }
    }

    return items
}

type UpdateReviewers = (
    content: Record<string, string>[],
    optimistic: EnrichedReviewer[],
    action: Extract<ReviewerEditActionEnumApi, 'add' | 'remove'>,
    removal?: ReviewerRemoval
) => void

/**
 * Remove suggested reviewers, optimistically, and record each removal. One implementation for
 * the picker's untoggle and the detail section's per-row remove, so the write payload and
 * the analytics cannot diverge.
 */
export function removeSuggestedReviewers({
    report,
    surface,
    targets,
    reviewers,
    updateReviewers,
    removal,
}: {
    report: SignalReport
    surface: InboxReportActionSurface
    targets: EnrichedReviewer[]
    reviewers: EnrichedReviewer[]
    removal?: ReviewerRemoval
    updateReviewers: UpdateReviewers
}): void {
    for (const target of targets) {
        captureInboxReportAction({
            report,
            actionType: 'remove_suggested_reviewer',
            surface,
            // pinned: analytics property names — renaming breaks dashboards
            extra: {
                suggested_reviewer_login: target.github_login || undefined,
                suggested_reviewer_uuid: target.user?.uuid,
                removal_reason: removal?.reason ?? undefined,
                has_removal_note: removal ? !!removal.note?.trim() : undefined,
            },
        })
    }
    const removed = new Set(targets)
    const next = reviewers.filter((reviewer) => !removed.has(reviewer))
    updateReviewers(reviewersToWriteContent(targets), next, 'remove', removal)
}

/** Add an org member as a suggested reviewer, or remove them when they already are one. Shared by both reviewer pickers. */
export function toggleSuggestedReviewer({
    report,
    surface,
    option,
    reviewers,
    updateReviewers,
}: {
    report: SignalReport
    surface: InboxReportActionSurface
    option: AvailableReviewerOption
    reviewers: EnrichedReviewer[]
    updateReviewers: UpdateReviewers
}): void {
    const existing = reviewers.find((r) => reviewerMatchesOption(r, option))
    if (existing) {
        removeSuggestedReviewers({ report, surface, targets: [existing], reviewers, updateReviewers })
        return
    }
    const optimisticEntry: EnrichedReviewer = {
        // The picker adds a PostHog member, whose GitHub login (if any) the server fills in.
        github_login: null,
        user_uuid: option.user_uuid,
        github_name: option.name || null,
        relevant_commits: [],
        source_label: 'Added by teammate',
        user: {
            id: 0,
            uuid: option.user_uuid,
            email: option.email,
            first_name: option.name,
            last_name: '',
        },
    }
    const next = [...reviewers, optimisticEntry]
    captureInboxReportAction({
        report,
        actionType: 'add_suggested_reviewer',
        surface,
        // The web option carries only the PostHog user uuid, never a GitHub login, so record it
        // under suggested_reviewer_uuid to match the shared cross-client event contract.
        extra: { suggested_reviewer_uuid: option.user_uuid },
    })
    updateReviewers([{ user_uuid: option.user_uuid }], next, 'add')
}

/** The heading and removal reasons of a reviewer's row menu, worded for your own row or a teammate's. */
export function reviewerRemovalMenu(
    reviewer: EnrichedReviewer,
    displayName: string,
    currentUserUuid: string | undefined
): { title: string; reasons: ReturnType<typeof reviewerRemovalReasonOptions> } {
    const isSelf = !!currentUserUuid && (reviewer.user?.uuid ?? reviewer.user_uuid) === currentUserUuid
    return {
        title: isSelf ? 'Remove yourself' : `Remove ${displayName}`,
        reasons: reviewerRemovalReasonOptions(isSelf),
    }
}

/** The source tags of a reason group: scouts collapse into one tag, other sources show once each. */
export function reviewerReasonGroupSources(
    reviewers: EnrichedReviewer[],
    reason: string
): { scoutNames: string[]; otherSourceLabels: string[] } {
    const scoutNames = new Set<string>()
    const otherSourceLabels = new Set<string>()
    for (const reviewer of reviewers) {
        const sourceLabel = getReviewerSourceLabel(reviewer)
        if (isScoutReviewer(reviewer)) {
            scoutNames.add(sourceLabel)
        } else if (sourceLabel !== 'Added by teammate' || !reason.startsWith('Added by ')) {
            otherSourceLabels.add(sourceLabel)
        }
    }
    return { scoutNames: [...scoutNames], otherSourceLabels: [...otherSourceLabels] }
}
