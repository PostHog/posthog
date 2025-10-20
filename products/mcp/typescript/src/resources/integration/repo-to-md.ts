import { unzipSync, strFromU8, Unzipped } from 'fflate'

const DEFAULT_SKIP_PATTERNS = [
    '.json',
    '.yaml',
    '.png',
    '.jpg',
    '.jpeg',
    '.gif',
    '.ico',
    '.svg',
    '.woff',
    '.woff2',
    '.ttf',
    '.eot',
    '.pdf',
    '.zip',
    '.tar',
    '.gz',
    '.exe',
    '.dll',
    '.so',
    '.dylib',
    '.DS_Store',
    'node_modules/',
    '.git/',
    '.gitignore',
    '.next/',
    '.css',
    '.scss',
    '.sass',
    '.less',
    '.styl',
    '.stylus',
    '.pcss',
    '.postcss',
    '.tailwindcss',
    'eslint',
]

export interface ConvertRepoOptions {
    /** The URL to the ZIP archive of the repository */
    zipUrl: string
    /** The framework name (used in the title) */
    frameworkName: string
    /** File extensions and paths to skip (e.g., [".json", "node_modules/"]) */
    skipPatterns?: string[]
}

export interface ConvertSubfolderOptions {
    /** Pre-fetched and unzipped repository contents */
    unzippedRepo: Unzipped
    /** The subfolder path to extract (e.g., "nextjs-app") */
    subfolderPath: string
    /** The framework name (used in the title) */
    frameworkName: string
    /** The repository URL for reference */
    repoUrl?: string
    /** File extensions and paths to skip (e.g., [".json", "node_modules/"]) */
    skipPatterns?: string[]
}

function buildMarkdownHeader(
    frameworkName: string,
    repoUrl: string,
    subfolderPath?: string
): string {
    let markdown = `# PostHog ${frameworkName.charAt(0).toUpperCase() + frameworkName.slice(1)} Example Project\n\n`
    markdown += `Repository: ${repoUrl}\n`
    if (subfolderPath) {
        markdown += `Path: ${subfolderPath}\n`
    }
    markdown += '\n---\n\n'
    return markdown
}

function fileToMarkdown(cleanPath: string, content: string, extension: string): string {
    let markdown = `## ${cleanPath}\n\n`
    markdown += `\`\`\`${extension}\n`
    markdown += content
    markdown += '\n```\n\n'
    return markdown
}

function processFiles(
    unzipped: Unzipped,
    filePaths: string[],
    skipPatterns: string[],
    pathTransform: (path: string) => string
): string {
    let markdown = ''

    for (const filePath of filePaths) {
        if (filePath.endsWith('/')) continue
        if (skipPatterns.some((pattern) => filePath.includes(pattern))) continue

        try {
            const fileData = unzipped[filePath]
            if (!fileData) continue

            const content = strFromU8(fileData)
            const extension = filePath.split('.').pop() || ''
            const cleanPath = pathTransform(filePath)

            markdown += fileToMarkdown(cleanPath, content, extension)
        } catch (e) {
            // Skip files that can't be decoded as text
        }
    }

    return markdown
}

/**
 * Fetches a GitHub repository ZIP and converts it to a markdown document
 * with all source files included as code blocks
 */
export async function convertRepoToMarkdown(options: ConvertRepoOptions): Promise<string> {
    const { zipUrl, frameworkName, skipPatterns = DEFAULT_SKIP_PATTERNS } = options

    const response = await fetch(zipUrl)
    if (!response.ok) {
        throw new Error(`Failed to fetch repository: ${response.statusText}`)
    }

    const arrayBuffer = await response.arrayBuffer()
    const uint8Array = new Uint8Array(arrayBuffer)
    const unzipped = unzipSync(uint8Array)

    const repoUrl = zipUrl.replace('/archive/refs/heads/main.zip', '')
    const sortedPaths = Object.keys(unzipped).sort()

    let markdown = buildMarkdownHeader(frameworkName, repoUrl)
    markdown += processFiles(unzipped, sortedPaths, skipPatterns, (filePath) =>
        filePath.replace(/^[^/]+\//, '')
    )

    return markdown
}

/**
 * Converts a specific subfolder from a pre-fetched ZIP to markdown
 */
export function convertSubfolderToMarkdown(options: ConvertSubfolderOptions): string {
    const {
        unzippedRepo,
        subfolderPath,
        frameworkName,
        repoUrl = 'https://github.com/PostHog/examples',
        skipPatterns = DEFAULT_SKIP_PATTERNS,
    } = options

    const sortedPaths = Object.keys(unzippedRepo)
        .filter((path) => {
            const pathParts = path.split('/')
            if (pathParts.length < 2) return false

            const relativePath = pathParts.slice(1).join('/')
            return relativePath.startsWith(subfolderPath + '/')
        })
        .sort()

    let markdown = buildMarkdownHeader(frameworkName, repoUrl, subfolderPath)
    markdown += processFiles(unzippedRepo, sortedPaths, skipPatterns, (filePath) => {
        const pathParts = filePath.split('/')
        const relativePath = pathParts.slice(1).join('/')
        return relativePath.replace(subfolderPath + '/', '')
    })

    return markdown
}
