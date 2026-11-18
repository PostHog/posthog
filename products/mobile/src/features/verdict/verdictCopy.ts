import type { PullRequestView } from '@/model/types'

// Copy mirrors `ResolveReportDialog.tsx` and `DismissReportDialog.tsx` in `products/signals/frontend/inbox/`.

export interface VerdictCopy {
    title: string
    description: string
    noteInfo: string
    notePlaceholder: string
    submitLabel: string
}

const OPEN_PR_SENTENCE = ' The pull request opened for this report is closed.'

function quotedTitle(reportTitle: string): string {
    return `"${reportTitle.trim() ? reportTitle.trim() : 'Untitled report'}"`
}

/** Matches the web inbox: a PR counts as open until it is merged or closed, so an unknown state counts too. */
export function hasOpenPullRequest(pullRequests: readonly PullRequestView[]): boolean {
    return pullRequests.some((pullRequest) => pullRequest.state !== 'merged' && pullRequest.state !== 'closed')
}

export function resolveCopy(reportTitle: string, hasOpenPr: boolean): VerdictCopy {
    return {
        title: `Resolve report ${quotedTitle(reportTitle)}?`,
        description: `This marks the report as done. If the issue comes back, you get a new report linked to this one.${
            hasOpenPr ? OPEN_PR_SENTENCE : ''
        }`,
        noteInfo: 'Optional. A link to the fix helps anyone who reads this report later.',
        notePlaceholder: 'Link to the pull request or commit, or what fixed it.',
        submitLabel: 'Resolve report',
    }
}

export function dismissCopy(reportTitle: string, hasOpenPr: boolean): VerdictCopy {
    return {
        title: `Dismiss report ${quotedTitle(reportTitle)}?`,
        description: `This report leaves your inbox. Your feedback is saved on the report, and your note goes to the agent that filed it.${
            hasOpenPr ? OPEN_PR_SENTENCE : ''
        }`,
        noteInfo: 'Optional. The agent reads it on its next run.',
        notePlaceholder: 'What made this report wrong, or not worth fixing?',
        submitLabel: 'Dismiss & teach the agent',
    }
}
