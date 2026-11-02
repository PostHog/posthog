import { urls } from 'scenes/urls'

import type { RepoApi } from '../generated/api.schemas'
import { findRepoByFullName } from './repoIds'
import { runPath, splitRepoFullName } from './repoPaths'

export type RepoPage = 'runs' | 'snapshots' | 'flakiness'

// Visual review URLs used to name a repo by UUID. Links in PR comments, Slack and bookmarks still do,
// so each old shape forwards to the owner/name path of the same page.
export type LegacyRoute =
    | { kind: 'repoPage'; repoId: string; page: RepoPage }
    | { kind: 'snapshotHistory'; repoId: string; runType: string; identifier: string }
    | { kind: 'run'; runId: string }

export interface ForwardUrl {
    path: string
    searchParams: Record<string, any>
    hashParams: Record<string, any>
}

function legacyPath(route: LegacyRoute, repoFullName: string): string {
    switch (route.kind) {
        case 'repoPage':
            if (route.page === 'snapshots') {
                return urls.visualReviewSnapshotOverview(...splitRepoFullName(repoFullName))
            }
            if (route.page === 'flakiness') {
                return urls.visualReviewFlakiness(...splitRepoFullName(repoFullName))
            }
            return urls.visualReviewRepoRuns(...splitRepoFullName(repoFullName))
        case 'snapshotHistory':
            return urls.visualReviewSnapshotHistory(...splitRepoFullName(repoFullName), route.runType, route.identifier)
        case 'run':
            return runPath(route.runId, repoFullName)
    }
}

export function legacyForwardUrl(
    route: LegacyRoute,
    repoFullName: string,
    searchParams: Record<string, any>,
    hashParams: Record<string, any>
): ForwardUrl {
    const path = legacyPath(route, repoFullName)
    // Old PR comments link a snapshot as `?snapshot=<id>`. The run page keeps its selection in the hash.
    const { snapshot, ...otherSearchParams } = searchParams
    if (route.kind === 'run' && snapshot && !hashParams.snapshot) {
        return { path, searchParams: otherSearchParams, hashParams: { ...hashParams, snapshot } }
    }
    return { path, searchParams, hashParams }
}

// `/visual-review` opens the repo this project used last, so a multi-repo team lands where it left off.
export function pickLandingRepo(repos: RepoApi[], lastRepoFullName: string | null): RepoApi | null {
    const lastRepo = lastRepoFullName ? findRepoByFullName(repos, lastRepoFullName) : null
    return lastRepo ?? repos[0] ?? null
}
