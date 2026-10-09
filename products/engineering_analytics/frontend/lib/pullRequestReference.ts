import type { GitHubSourceApi } from '../generated/api.schemas'

/** A pull request that free text names. A bare number names no repository. */
export type PullRequestReference =
    | { kind: 'link' | 'repo_number'; owner: string; repo: string; number: number }
    | { kind: 'number'; number: number }

export interface PullRequestTarget {
    owner: string
    repo: string
    number: number
    /** The connected source that syncs the repository. Null when no connected source does. */
    sourceId: string | null
}

// The host must start the text or follow a character that a host name or a path cannot contain. Without
// that guard `notgithub.com`, `gist.github.com`, and a GitHub address in the path of another site all match.
const LINK = /(?:^|[^\w./-])(?:https?:\/\/)?(?:www\.)?github\.com\/([\w-]+)\/([\w.-]+)\/pull\/(\d+)\b/i
const REPO_NUMBER = /^([\w-]+)\/([\w.-]+)#(\d+)$/
const NUMBER = /^#?(\d+)$/

export function parsePullRequestReference(text: string): PullRequestReference | null {
    const trimmed = text.trim()
    const link = LINK.exec(trimmed)
    const named = link ?? REPO_NUMBER.exec(trimmed)
    const digits = named?.[3] ?? NUMBER.exec(trimmed)?.[1]
    const number = digits ? Number(digits) : 0
    // Past the safe integer range a number prints in exponent form, which is not a pull request number.
    if (!Number.isSafeInteger(number) || number < 1) {
        return null
    }
    return named
        ? { kind: link ? 'link' : 'repo_number', owner: named[1], repo: named[2], number }
        : { kind: 'number', number }
}

/** Where a reference opens. A bare number takes the repository of `pickedSource`, else of the only connected
 *  source. The result is null when a bare number has neither. */
export function resolvePullRequestTarget(
    reference: PullRequestReference,
    sources: GitHubSourceApi[],
    pickedSource: GitHubSourceApi | null
): PullRequestTarget | null {
    if (reference.kind === 'number') {
        const source = pickedSource ?? (sources.length === 1 ? sources[0] : null)
        const [owner, repo] = source?.repo.split('/') ?? []
        return source && owner && repo ? { owner, repo, number: reference.number, sourceId: source.id } : null
    }
    // GitHub ignores case in repository names, so match that way and keep the casing the source reports.
    const fullName = `${reference.owner}/${reference.repo}`.toLowerCase()
    const source = sources.find(({ repo }) => repo.toLowerCase() === fullName)
    const [owner, repo] = source ? source.repo.split('/') : [reference.owner, reference.repo]
    return { owner, repo, number: reference.number, sourceId: source?.id ?? null }
}
