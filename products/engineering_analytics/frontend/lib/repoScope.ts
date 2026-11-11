// Every page reads one repository, and the URL names it: /engineering-analytics/repos/:owner/:name/...
// These rules decide which repository a repo-less URL forwards to, and where switching repository lands.

import type { GitHubSourceApi } from '../generated/api.schemas'
import { repoPrefix } from './repoUrls'

const PRODUCT_ROOT = '/engineering-analytics'
const REPO_PATH = /^\/engineering-analytics\/repos\/([^/]+)\/([^/]+)(\/.*)?$/
// Pages about one entity of a repository. Another repository has no such entity, so switching repository
// from one of them lands on the tab that lists them.
const ENTITY_TAB: [RegExp, string][] = [
    [/^\/pull-requests\/[^/]+/, '/pull-requests'],
    [/^\/actions\//, '/workflows'],
]

// A hand-typed URL can carry a malformed escape such as %zz, and decodeURIComponent throws on it.
function decodeSegment(segment: string): string {
    try {
        return decodeURIComponent(segment)
    } catch {
        return segment
    }
}

/** The 'owner/name' a repo path names, or null for a repo-less path. */
export function repoFromPath(pathname: string): string | null {
    const match = REPO_PATH.exec(pathname)
    return match ? `${decodeSegment(match[1])}/${decodeSegment(match[2])}` : null
}

/** The repository a repo-less URL forwards to: the one it asks for, else the last one used, else the
 *  backend's default (the first synced repository). Null when no connected repository has a name, or when
 *  the URL asks for a legacy source that names none: that page stays repo-less and reads the source. */
export function pickForwardRepo(
    sources: GitHubSourceApi[],
    requested: { repo?: string | null; sourceId?: string | null },
    lastRepo: string | null
): string | null {
    const named = sources.filter((source) => source.repo)
    const known = (repo: string | null | undefined): string | null =>
        named.find((source) => source.repo.toLowerCase() === repo?.toLowerCase())?.repo ?? null
    const requestedRepo = known(requested.repo)
    if (requestedRepo) {
        return requestedRepo
    }
    const ofSource = requested.sourceId ? sources.filter((source) => source.id === requested.sourceId) : []
    if (ofSource.length > 0 && ofSource.every((source) => !source.repo)) {
        return null
    }
    const namedOfSource = ofSource.filter((source) => source.repo)
    return (
        (namedOfSource.find((source) => source.synced) ?? namedOfSource[0])?.repo ??
        known(lastRepo) ??
        (named.find((source) => source.synced) ?? named[0])?.repo ??
        null
    )
}

/** The repo path a repo-less product path forwards to: /engineering-analytics/<rest> keeps its <rest>. */
export function repoPathFor(pathname: string, repo: string): string {
    const [repoOwner, repoName] = repo.split('/')
    const rest = pathname.startsWith(PRODUCT_ROOT) ? pathname.slice(PRODUCT_ROOT.length) : ''
    return `${repoPrefix(repoOwner, repoName)}${rest && rest !== '/' ? rest : '/overview'}`
}

/** Where switching to `repo` lands: the same page in that repository, or the list tab for an entity page.
 *  A null repo is a legacy source that names none, so it lands on the repo-less form of that page. */
export function switchRepoPath(pathname: string, repo: string | null): string {
    const match = REPO_PATH.exec(pathname)
    if (!match) {
        return repo ? repoPathFor(pathname, repo) : pathname
    }
    const rest = match[3] ?? '/overview'
    const entityTab = ENTITY_TAB.find(([pattern]) => pattern.test(rest))?.[1]
    if (!repo) {
        return `${PRODUCT_ROOT}${entityTab ?? rest}`
    }
    const [repoOwner, repoName] = repo.split('/')
    return `${repoPrefix(repoOwner, repoName)}${entityTab ?? rest}`
}
