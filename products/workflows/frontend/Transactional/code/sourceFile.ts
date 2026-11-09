export type SourceFileHost = 'github' | 'gitlab' | 'other'

export interface SourceFile {
    url: string
    host: SourceFileHost
    /** Empty on another host, where the path carries the whole link. */
    repo: string
    path: string
    ref: string
}

const GITHUB_FILE = /^\/([^/]+\/[^/]+)\/blob\/([^/]+)\/(.+)$/
// GitLab groups nest, so the repository is everything before the `/-/blob/` marker.
const GITLAB_FILE = /^\/(.+?)\/-\/blob\/([^/]+)\/(.+)$/

/** Reads the repository, path and ref out of a GitHub or GitLab file link. */
export function parseSourceFile(url: string): SourceFile {
    const parsed = safeUrl(url)
    const host = parsed?.hostname.replace(/^www\./, '')
    const match =
        host === 'github.com'
            ? parsed?.pathname.match(GITHUB_FILE)
            : host === 'gitlab.com'
              ? parsed?.pathname.match(GITLAB_FILE)
              : null
    if (parsed && match) {
        return {
            url,
            host: host === 'github.com' ? 'github' : 'gitlab',
            repo: match[1],
            ref: safeDecode(match[2]),
            path: safeDecode(match[3]),
        }
    }
    const path = parsed ? `${parsed.hostname}${parsed.pathname}`.replace(/\/$/, '') : url
    return { url, host: 'other', repo: '', path, ref: '' }
}

export function repoUrl(file: SourceFile): string | null {
    return file.host === 'other' ? null : `https://${file.host}.com/${file.repo}`
}

/** A commit SHA is shortened the way the code hosts show it. */
export function displayRef(ref: string): string {
    return /^[0-9a-f]{7,40}$/i.test(ref) ? ref.slice(0, 7) : ref
}

// A stray `%` in a file name is not an escape, so text that fails to decode is shown as it was typed.
function safeDecode(text: string): string {
    try {
        return decodeURIComponent(text)
    } catch {
        return text
    }
}

function safeUrl(url: string): URL | null {
    try {
        return new URL(url)
    } catch {
        return null
    }
}
