// Default repository configuration
export const DEFAULT_OWNER = 'PostHog'
export const DEFAULT_REPO = 'posthog'
export const DEFAULT_BRANCH = 'master'

export interface RepositoryConfig {
    owner: string
    repo: string
    branch: string
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

export async function loadRepositoryTree(
    owner: string = DEFAULT_OWNER,
    repo: string = DEFAULT_REPO,
    branch: string = DEFAULT_BRANCH
): Promise<GitHubTreeResponse> {
    const branchResponse = await fetch(`https://api.github.com/repos/${owner}/${repo}/branches/${branch}`)
    const branchData = await branchResponse.json()
    const sha = branchData.commit.sha

    const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/git/trees/${sha}?recursive=1`)

    return (await response.json()) as GitHubTreeResponse
}

export async function loadFileContent(
    filePath: string,
    owner: string = DEFAULT_OWNER,
    repo: string = DEFAULT_REPO
): Promise<GitHubFileContent> {
    const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents/${filePath}`)
    const fileContent = (await response.json()) as GitHubFileContent

    if (fileContent.encoding === 'base64') {
        fileContent.content = atob(fileContent.content)
    }

    return fileContent
}
