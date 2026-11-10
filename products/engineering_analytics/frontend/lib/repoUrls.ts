export function repoPrefix(repoOwner: string, repoName: string): string {
    return `/engineering-analytics/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}`
}
