// The manifest imports this module, so it must stay free of app and API imports.

export function repoPath(repoFullName: string): string {
    const slash = repoFullName.indexOf('/')
    const owner = slash === -1 ? repoFullName : repoFullName.slice(0, slash)
    const name = slash === -1 ? '' : repoFullName.slice(slash + 1)
    return `/visual_review/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`
}

// Route params arrive still encoded, so decode each segment before joining them back into a full name.
export function repoFullNameFromParams(repoOwner: string | undefined, repoName: string | undefined): string {
    return `${decodeURIComponent(repoOwner ?? '')}/${decodeURIComponent(repoName ?? '')}`
}
