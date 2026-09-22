// Where a version came from. The CLI resolves this itself, because only the client can see the
// CI variables and the git checkout.
//
// Order: the CI provider, then local git, then nothing at all. Never a mixture: a commit from one
// place and a branch from another describes a state that never existed.

import { spawnSync } from 'node:child_process'
import { realpathSync } from 'node:fs'
import { isAbsolute, relative, resolve } from 'node:path'

/** The seven keys the API accepts. Anything that does not resolve is left out. */
export interface Source {
    readonly commit?: string
    readonly ref?: string
    readonly repository?: string
    readonly path?: string
    readonly run_url?: string
    readonly author?: string
    readonly message?: string
}

export interface SourceOptions {
    readonly env: Readonly<Record<string, string | undefined>>
    /** The file as it was given on the command line. */
    readonly filePath: string
    readonly cwd: string
}

const FULL_SHA = /^[0-9a-f]{40}$/

function git(cwd: string, args: readonly string[]): string | undefined {
    const result = spawnSync('git', [...args], { cwd, encoding: 'utf8' })
    if (result.status !== 0 || typeof result.stdout !== 'string') {
        return undefined
    }
    const value = result.stdout.trim()
    return value === '' ? undefined : value
}

/**
 * `git@github.com:acme/flows.git` and `https://github.com/acme/flows` both become `github.com/acme/flows`.
 *
 * @param url - The remote URL, in SCP or HTTPS form.
 */
export function repositoryFromRemote(url: string): string | undefined {
    const trimmed = url.trim().replace(/\.git$/, '')
    const scp = /^[^@/]+@([^:]+):(.+)$/.exec(trimmed)
    if (scp !== null) {
        return `${scp[1]}/${scp[2]}`
    }
    try {
        const parsed = new URL(trimmed)
        return `${parsed.host}${parsed.pathname}`.replace(/\/+$/, '')
    } catch {
        return undefined
    }
}

function hostOf(serverUrl: string): string | undefined {
    try {
        return new URL(serverUrl).host
    } catch {
        return undefined
    }
}

function real(path: string): string {
    try {
        return realpathSync(path)
    } catch {
        return path
    }
}

function repoRelativePath(options: SourceOptions): string | undefined {
    const absolute = isAbsolute(options.filePath) ? options.filePath : resolve(options.cwd, options.filePath)
    const top = git(options.cwd, ['rev-parse', '--show-toplevel'])
    const root = top ?? options.env.GITHUB_WORKSPACE ?? options.env.CI_PROJECT_DIR
    if (root === undefined) {
        return undefined
    }
    // Both sides go through realpath, because a checkout reached through a symlink would otherwise
    // read as a file outside the repository.
    const inside = relative(real(root), real(absolute))
    // Forward slashes always, so the same file pushed from Windows and from CI reads as one path
    // rather than as a move.
    return inside.startsWith('..') ? undefined : inside.split('\\').join('/')
}

/**
 * The author and the subject line, which only the checkout holds.
 *
 * @param cwd - The checkout to ask.
 * @param commit - The commit sha to describe.
 */
function commitDetails(cwd: string, commit: string): { author?: string; message?: string } {
    const author = git(cwd, ['log', '-1', '--format=%an', commit])
    const message = git(cwd, ['log', '-1', '--format=%s', commit])
    return {
        ...(author === undefined ? {} : { author }),
        ...(message === undefined ? {} : { message }),
    }
}

function defined(source: Source): Source | null {
    const entries = Object.entries(source).filter(([, value]) => value !== undefined && value !== '')
    return entries.length === 0 ? null : (Object.fromEntries(entries) as Source)
}

function fromGitHubActions(options: SourceOptions): Source | null {
    const env = options.env
    const server = env.GITHUB_SERVER_URL ?? 'https://github.com'
    const host = hostOf(server)
    const repository = host !== undefined && env.GITHUB_REPOSITORY ? `${host}/${env.GITHUB_REPOSITORY}` : undefined
    const runUrl =
        env.GITHUB_REPOSITORY && env.GITHUB_RUN_ID
            ? `${server.replace(/\/+$/, '')}/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID}`
            : undefined

    // On a pull_request event GITHUB_SHA is a merge commit that exists in no branch, and
    // GITHUB_REF_NAME is `123/merge`. A permalink to either points at nothing, so the run records
    // the branch it came from and no commit at all.
    const onPullRequest = env.GITHUB_EVENT_NAME === 'pull_request'
    const commit = onPullRequest ? undefined : env.GITHUB_SHA
    const ref = onPullRequest ? env.GITHUB_HEAD_REF : env.GITHUB_REF_NAME

    return defined({
        ...(commit !== undefined && FULL_SHA.test(commit) ? { commit, ...commitDetails(options.cwd, commit) } : {}),
        ...(ref === undefined ? {} : { ref }),
        ...(repository === undefined ? {} : { repository }),
        ...(runUrl === undefined ? {} : { run_url: runUrl }),
        ...withPath(options),
    })
}

function fromGitLab(options: SourceOptions): Source | null {
    const env = options.env
    const repository =
        env.CI_SERVER_HOST && env.CI_PROJECT_PATH ? `${env.CI_SERVER_HOST}/${env.CI_PROJECT_PATH}` : undefined
    // CI_COMMIT_BRANCH is unset on a merge request pipeline, where CI_COMMIT_REF_NAME is
    // `refs/merge-requests/<iid>/merge`. That is a ref nobody can open, so the run records none.
    const ref = env.CI_COMMIT_BRANCH
    const commit = env.CI_COMMIT_SHA
    const author = env.CI_COMMIT_AUTHOR?.replace(/\s*<[^>]*>\s*$/, '')

    return defined({
        ...(commit !== undefined && FULL_SHA.test(commit) ? { commit } : {}),
        ...(ref === undefined ? {} : { ref }),
        ...(repository === undefined ? {} : { repository }),
        ...(env.CI_PIPELINE_URL === undefined ? {} : { run_url: env.CI_PIPELINE_URL }),
        ...(author === undefined ? {} : { author }),
        ...(env.CI_COMMIT_TITLE === undefined ? {} : { message: env.CI_COMMIT_TITLE }),
        ...withPath(options),
    })
}

function fromGit(options: SourceOptions): Source | null {
    const commit = git(options.cwd, ['rev-parse', 'HEAD'])
    if (commit === undefined || !FULL_SHA.test(commit)) {
        return null
    }
    const branch = git(options.cwd, ['rev-parse', '--abbrev-ref', 'HEAD'])
    const remote = git(options.cwd, ['remote', 'get-url', 'origin'])
    const repository = remote === undefined ? undefined : repositoryFromRemote(remote)
    return defined({
        commit,
        // A detached HEAD reports the literal `HEAD`, which names no branch.
        ...(branch === undefined || branch === 'HEAD' ? {} : { ref: branch }),
        ...(repository === undefined ? {} : { repository }),
        ...commitDetails(options.cwd, commit),
        ...withPath(options),
    })
}

function withPath(options: SourceOptions): { path?: string } {
    const path = repoRelativePath(options)
    return path === undefined ? {} : { path }
}

/**
 * The source for this run, or null when neither CI nor a checkout can say.
 *
 * @param options - The environment, the file path and the working directory to resolve from.
 */
export function resolveSource(options: SourceOptions): Source | null {
    if (options.env.GITHUB_ACTIONS === 'true') {
        return fromGitHubActions(options)
    }
    if (options.env.GITLAB_CI === 'true') {
        return fromGitLab(options)
    }
    return fromGit(options)
}
