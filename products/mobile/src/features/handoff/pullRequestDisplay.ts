import type { PullRequestView } from '@/model/types'

export const PULL_REQUEST_STATE_LABELS: Record<PullRequestView['state'], string> = {
    open: 'Open',
    draft: 'Draft',
    closed: 'Closed',
    merged: 'Merged',
    unknown: 'Status unavailable',
}

const REVIEW_LABELS: Record<NonNullable<PullRequestView['reviewDecision']>, string> = {
    approved: 'Approved',
    changes_requested: 'Changes requested',
    review_required: 'Review required',
}

export function pullRequestTitle(pullRequest: PullRequestView): string {
    return pullRequest.title ?? (pullRequest.number === undefined ? 'Pull request' : `PR #${pullRequest.number}`)
}

export function pullRequestIdentity(pullRequest: PullRequestView): string {
    const repository = /github\.com\/([^/]+\/[^/]+)\/pull\//.exec(pullRequest.url)?.[1]
    return [repository, pullRequest.number === undefined ? undefined : `#${pullRequest.number}`]
        .filter(Boolean)
        .join(' · ')
}

export function pullRequestDetails(pullRequest: PullRequestView): string {
    return [
        pullRequest.reviewDecision ? REVIEW_LABELS[pullRequest.reviewDecision] : undefined,
        pullRequest.filesChanged === undefined
            ? undefined
            : `${pullRequest.filesChanged} ${pullRequest.filesChanged === 1 ? 'file' : 'files'}`,
    ]
        .filter(Boolean)
        .join(' · ')
}
