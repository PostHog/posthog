const OWNER = 'PostHog';
const REPO = 'posthog';
const BRANCH = 'master';

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

export async function loadRepositoryTree(): Promise<GitHubTreeResponse> {
    // NOTE(Marce): In the future of course we'll make this properly
    const branchResponse = await fetch(
        `https://api.github.com/repos/${OWNER}/${REPO}/branches/${BRANCH}`
    )
    const branchData = await branchResponse.json()
    const sha = branchData.commit.sha

    const response = await fetch(
        `https://api.github.com/repos/${OWNER}/${REPO}/git/trees/${sha}?recursive=1`
    )

    return (await response.json()) as GitHubTreeResponse
}

export async function loadFileContent(filePath: string): Promise<GitHubFileContent> {
    const response = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${filePath}`)
    const fileContent = (await response.json()) as GitHubFileContent

    if (fileContent.encoding === 'base64') {
        fileContent.content = atob(fileContent.content)
    }

    return fileContent
}
