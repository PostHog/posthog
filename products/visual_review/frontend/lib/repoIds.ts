import { visualReviewReposList } from '../generated/api'
import type { RepoApi } from '../generated/api.schemas'

const REPOS_PAGE_SIZE = 100

export class RepoNotFoundError extends Error {
    constructor(repoRef: string) {
        super(`No visual review repo matches ${repoRef}`)
        this.name = 'RepoNotFoundError'
    }
}

// GitHub treats owner and repo names as case-insensitive, so a link typed by hand still resolves.
// A repo that was deleted and connected again has two rows with the same name, and the newest one is live.
export function findRepoByFullName(repos: RepoApi[], repoFullName: string): RepoApi | null {
    const wanted = repoFullName.toLowerCase()
    let newest: RepoApi | null = null
    for (const repo of repos) {
        if (repo.repo_full_name.toLowerCase() !== wanted) {
            continue
        }
        if (!newest || new Date(repo.created_at).getTime() > new Date(newest.created_at).getTime()) {
            newest = repo
        }
    }
    return newest
}

async function fetchAllRepos(projectId: string): Promise<RepoApi[]> {
    const repos: RepoApi[] = []
    for (;;) {
        const page = await visualReviewReposList(projectId, { limit: REPOS_PAGE_SIZE, offset: repos.length })
        repos.push(...page.results)
        if (!page.next || page.results.length === 0) {
            return repos
        }
    }
}

// One shared request per project. Every repo-scoped logic on a page resolves the same name at mount,
// so sharing the request keeps that to a single list call.
const repoListRequests = new Map<string, Promise<RepoApi[]>>()

function loadRepos(projectId: string, refresh: boolean): Promise<RepoApi[]> {
    const cached = repoListRequests.get(projectId)
    if (cached && !refresh) {
        return cached
    }
    const request = fetchAllRepos(projectId)
    repoListRequests.set(projectId, request)
    // A failed request must not stay cached, or every later lookup fails without a retry.
    request.catch(() => {
        if (repoListRequests.get(projectId) === request) {
            repoListRequests.delete(projectId)
        }
    })
    return request
}

// Lookups that miss at the same moment share one refresh, so a page of repo-scoped logics makes one extra call.
const repoListRefreshes = new Map<string, Promise<RepoApi[]>>()

function refreshRepos(projectId: string): Promise<RepoApi[]> {
    const pending = repoListRefreshes.get(projectId)
    if (pending) {
        return pending
    }
    const refresh = loadRepos(projectId, true)
    repoListRefreshes.set(projectId, refresh)
    const clear = (): void => {
        repoListRefreshes.delete(projectId)
    }
    refresh.then(clear, clear)
    return refresh
}

// The cached list can predate a repo connected a moment ago, so a miss on it fetches the list once more.
async function findRepo(projectId: string, matches: (repos: RepoApi[]) => RepoApi | null): Promise<RepoApi | null> {
    const wasCached = repoListRequests.has(projectId)
    const repo = matches(await loadRepos(projectId, false))
    if (repo || !wasCached) {
        return repo
    }
    return matches(await refreshRepos(projectId))
}

export async function resolveRepoId(projectId: string, repoFullName: string): Promise<string> {
    const repo = await findRepo(projectId, (repos) => findRepoByFullName(repos, repoFullName))
    if (!repo) {
        throw new RepoNotFoundError(repoFullName)
    }
    return repo.id
}

export async function resolveRepoFullName(projectId: string, repoId: string): Promise<string> {
    const repo = await findRepo(projectId, (repos) => repos.find((candidate) => candidate.id === repoId) ?? null)
    if (!repo) {
        throw new RepoNotFoundError(repoId)
    }
    return repo.repo_full_name
}

export function clearRepoIdCache(): void {
    repoListRequests.clear()
    repoListRefreshes.clear()
}
