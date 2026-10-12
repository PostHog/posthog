// Path builders the product manifest imports. Keep this module free of logic imports: the generated
// products.tsx loads it eagerly.

/** The path prefix of one repository's pages. */
export function repoPrefix(repoOwner: string, repoName: string): string {
    return `/engineering-analytics/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}`
}

/** A tab path inside `repo` ('owner/name'), or the repo-less path that forwards when there is none. */
export function repoTabUrl(tab: string, repo?: string | null): string {
    const [repoOwner, repoName] = repo?.split('/') ?? []
    return repoOwner && repoName ? `${repoPrefix(repoOwner, repoName)}/${tab}` : `/engineering-analytics/${tab}`
}
