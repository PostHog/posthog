import { PrStateEnumApi, TaskListItemApi, TaskRunDetailDTOApi, TaskSummaryDTOApi } from '../generated/api.schemas'

export interface TaskPullRequest {
    url: string
    /** The `owner/repo` part of the URL. */
    repository: string
    number: number
}

const GITHUB_HOSTS = new Set(['github.com', 'www.github.com'])
const PULL_REQUEST_PATH = /^\/([^/]+)\/([^/]+)\/pull\/(\d+)(?:\/|$)/

export function parsePullRequestUrl(raw: string): TaskPullRequest | null {
    let parsed: URL
    try {
        parsed = new URL(raw.trim())
    } catch {
        return null
    }
    if (parsed.protocol !== 'https:' || !GITHUB_HOSTS.has(parsed.hostname)) {
        return null
    }
    const match = PULL_REQUEST_PATH.exec(parsed.pathname)
    if (!match) {
        return null
    }
    const [, owner, repo, number] = match
    return {
        url: `https://github.com/${owner}/${repo}/pull/${number}`,
        repository: `${owner}/${repo}`,
        number: Number(number),
    }
}

/** Every GitHub pull request the run reported, without duplicates. The run's main `pr_url` comes first. */
export function taskPullRequests(output: TaskRunDetailDTOApi['output'] | undefined): TaskPullRequest[] {
    if (!output) {
        return []
    }
    const listed: unknown[] = Array.isArray(output.pr_urls) ? output.pr_urls : []
    const pullRequests: TaskPullRequest[] = []
    for (const candidate of [output.pr_url, ...listed]) {
        const pullRequest = typeof candidate === 'string' ? parsePullRequestUrl(candidate) : null
        if (pullRequest && !pullRequests.some((existing) => existing.url === pullRequest.url)) {
            pullRequests.push(pullRequest)
        }
    }
    return pullRequests
}

/** Like Desktop, the card shows two chips, or one when there are five or more. The rest go behind a "+N PRs" chip. */
export function splitPullRequests(pullRequests: TaskPullRequest[]): {
    visible: TaskPullRequest[]
    overflow: TaskPullRequest[]
} {
    const visibleCount = pullRequests.length >= 5 ? 1 : 2
    return { visible: pullRequests.slice(0, visibleCount), overflow: pullRequests.slice(visibleCount) }
}

const SPACE_PULL_REQUEST_LIMIT = 30

export interface SessionPullRequest<T> {
    pullRequest: TaskPullRequest
    /** The newest session that reported the pull request. */
    session: T
}

/** A space's pull requests for its PRs view, like PostHog Desktop's: newest session activity first, each PR once. */
export function spacePullRequests<T extends { pullRequests: TaskPullRequest[]; timestamp: string | null }>(
    sessions: T[],
    limit = SPACE_PULL_REQUEST_LIMIT
): SessionPullRequest<T>[] {
    const timeOf = (session: T): number => (session.timestamp ? Date.parse(session.timestamp) : 0)
    const byActivity = [...sessions].sort((first, second) => timeOf(second) - timeOf(first))
    const seen = new Set<string>()
    const result: SessionPullRequest<T>[] = []
    for (const session of byActivity) {
        for (const pullRequest of session.pullRequests) {
            if (result.length >= limit) {
                return result
            }
            if (!seen.has(pullRequest.url)) {
                seen.add(pullRequest.url)
                result.push({ pullRequest, session })
            }
        }
    }
    return result
}

/** `#123` when the pull request is in the task's repository, `repo#123` when it is in another one. */
export function pullRequestLabel(pullRequest: TaskPullRequest, taskRepository: string | null | undefined): string {
    const [, repoName] = pullRequest.repository.split('/')
    const task = taskRepository?.toLowerCase()
    const sameRepository = task === pullRequest.repository.toLowerCase() || task === repoName.toLowerCase()
    return sameRepository ? `#${pullRequest.number}` : `${repoName}#${pullRequest.number}`
}

/** Sessions whose latest run opened a pull request, the only ones the summaries endpoint can give a state for. */
export function sessionIdsWithPullRequests(tasks: TaskListItemApi[]): string[] {
    return tasks.filter((task) => taskPullRequests(task.latest_run?.output).length > 0).map((task) => task.id)
}

/** The known state of each run's main pull request, keyed by its normalized URL. */
export function pullRequestStates(summaries: TaskSummaryDTOApi[]): Record<string, PrStateEnumApi> {
    const states: Record<string, PrStateEnumApi> = {}
    for (const summary of summaries) {
        const run = summary.latest_run
        const pullRequest = run?.pr_url ? parsePullRequestUrl(run.pr_url) : null
        if (pullRequest && run?.pr_state && run.pr_state !== 'unknown') {
            states[pullRequest.url] = run.pr_state
        }
    }
    return states
}
