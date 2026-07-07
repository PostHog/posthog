export function githubPrUrl(repoOwner: string, repoName: string, number: number): string {
    return `https://github.com/${repoOwner}/${repoName}/pull/${number}`
}

/** GitHub has no stable by-name workflow URL, so link the Actions list filtered to the workflow. */
export function githubWorkflowUrl(repoOwner: string, repoName: string, workflowName: string): string {
    return `https://github.com/${repoOwner}/${repoName}/actions?query=${encodeURIComponent(`workflow:"${workflowName}"`)}`
}

export function githubRunUrl(repoOwner: string, repoName: string, runId: number): string {
    return `https://github.com/${repoOwner}/${repoName}/actions/runs/${runId}`
}

export function githubCommitUrl(repoOwner: string, repoName: string, sha: string): string {
    return `https://github.com/${repoOwner}/${repoName}/commit/${sha}`
}
