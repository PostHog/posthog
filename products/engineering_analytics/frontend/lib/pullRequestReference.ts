/** A pull request that free text names. A bare number names no repository. */
export type PullRequestReference =
    | { kind: 'link' | 'repo_number'; owner: string; repo: string; number: number }
    | { kind: 'number'; number: number }

export interface PullRequestTarget {
    owner: string
    repo: string
    number: number
    /** False when the pull request is in another repository than the one the page is scoped to. */
    inScope: boolean
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

/** Where a reference opens. A bare number opens in `scopedRepo`, the 'owner/name' the page is scoped to. The
 *  result is null when a bare number has no such repository. */
export function resolvePullRequestTarget(
    reference: PullRequestReference,
    scopedRepo: string | null
): PullRequestTarget | null {
    const [owner, repo] = scopedRepo?.split('/') ?? []
    const scoped = owner && repo ? { owner, repo, number: reference.number, inScope: true } : null
    if (reference.kind === 'number') {
        return scoped
    }
    // GitHub ignores case in repository names, so match that way and keep the casing the scope reports.
    const named = `${reference.owner}/${reference.repo}`.toLowerCase() === scopedRepo?.toLowerCase()
    return named && scoped
        ? scoped
        : { owner: reference.owner, repo: reference.repo, number: reference.number, inScope: false }
}
