import { getCurrentTeamId } from 'lib/utils/getAppContext'

// Default repository configuration
export const DEFAULT_REPO = 'posthog'
export const DEFAULT_BRANCH = 'master'

export interface RepositoryConfig {
    repo: string
    branch: string
}

export interface Repository {
    name: string
    full_name: string
}

export interface GitHubTreeItem {
    path: string
    mode: string
    type: 'blob' | 'tree'
    sha: string
    size?: number
    url: string
}

export interface GitHubTreeResponse {
    sha: string
    url: string
    tree: GitHubTreeItem[]
    truncated: boolean
}

export interface GitHubFileContent {
    name: string
    path: string
    sha: string
    size: number
    url: string
    html_url: string
    git_url: string
    download_url: string
    type: string
    content: string
    encoding: string
}

async function getApiUrl(endpoint: string): Promise<string> {
    const teamId = getCurrentTeamId()
    return `/api/projects/${teamId}/live_debugger_repo_browser/${endpoint}`
}

export async function loadRepositories(): Promise<Repository[]> {
    const url = await getApiUrl('repositories')
    const response = await fetch(url)

    if (!response.ok) {
        const error = await response.json()
        throw new Error(error.error || 'Failed to load repositories')
    }

    const data = await response.json()
    return data.repositories
}

export async function loadRepositoryTree(
    repo: string = DEFAULT_REPO,
    branch: string = DEFAULT_BRANCH
): Promise<GitHubTreeResponse> {
    const url = await getApiUrl(`tree?repo=${encodeURIComponent(repo)}&branch=${encodeURIComponent(branch)}`)
    const response = await fetch(url)

    if (!response.ok) {
        const error = await response.json()
        throw new Error(error.error || 'Failed to load repository tree')
    }

    return (await response.json()) as GitHubTreeResponse
}

export async function loadFileContent(
    filePath: string,
    repo: string = DEFAULT_REPO,
    branch: string = DEFAULT_BRANCH
): Promise<GitHubFileContent> {
    const url = await getApiUrl(
        `file?repo=${encodeURIComponent(repo)}&branch=${encodeURIComponent(branch)}&path=${encodeURIComponent(filePath)}`
    )
    const response = await fetch(url)

    if (!response.ok) {
        const error = await response.json()
        throw new Error(error.error || 'Failed to load file content')
    }

    return (await response.json()) as GitHubFileContent
}
