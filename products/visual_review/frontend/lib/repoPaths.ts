import { urls } from 'scenes/urls'

/** 'owner/name' as the owner and name the URL builders take. */
export function splitRepoFullName(repoFullName: string): [string, string] {
    const slash = repoFullName.indexOf('/')
    return slash === -1 ? [repoFullName, ''] : [repoFullName.slice(0, slash), repoFullName.slice(slash + 1)]
}

// Route params arrive still encoded, so decode each segment before joining them back into a full name.
export function repoFullNameFromParams(repoOwner: string | undefined, repoName: string | undefined): string {
    return `${decodeURIComponent(repoOwner ?? '')}/${decodeURIComponent(repoName ?? '')}`
}

/** A run inside its repository, or the run path that forwards while the repository is not known yet. */
export function runPath(runId: string, repoFullName: string | null | undefined): string {
    return repoFullName
        ? urls.visualReviewRepoRun(...splitRepoFullName(repoFullName), runId)
        : urls.visualReviewRun(runId)
}
