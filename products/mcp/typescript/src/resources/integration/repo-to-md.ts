import { unzipSync, strFromU8 } from 'fflate'

/**
 * Maps file extensions to their corresponding language identifiers for code blocks
 */
function getLanguageFromExtension(extension: string): string {
    const languageMap: Record<string, string> = {
        ts: 'typescript',
        tsx: 'typescript',
        js: 'javascript',
        jsx: 'javascript',
        json: 'json',
        md: 'markdown',
        css: 'css',
        scss: 'scss',
        html: 'html',
        yml: 'yaml',
        yaml: 'yaml',
        toml: 'toml',
        xml: 'xml',
        sh: 'bash',
        bash: 'bash',
        sql: 'sql',
        py: 'python',
        go: 'go',
        rs: 'rust',
        java: 'java',
        c: 'c',
        cpp: 'cpp',
        h: 'c',
        hpp: 'cpp',
    }
    return languageMap[extension.toLowerCase()] || extension
}

export interface ConvertRepoOptions {
    /** The URL to the ZIP archive of the repository */
    zipUrl: string
    /** The framework name (used in the title) */
    frameworkName: string
    /** File extensions and paths to skip (e.g., [".json", "node_modules/"]) */
    skipPatterns?: string[]
}

/**
 * Fetches a GitHub repository ZIP and converts it to a markdown document
 * with all source files included as code blocks
 */
export async function convertRepoToMarkdown(options: ConvertRepoOptions): Promise<string> {
    const {
        zipUrl,
        frameworkName,
        skipPatterns = [
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
            '.next/',
        ],
    } = options

    // Fetch the ZIP archive from GitHub
    const response = await fetch(zipUrl)

    if (!response.ok) {
        throw new Error(`Failed to fetch repository: ${response.statusText}`)
    }

    const arrayBuffer = await response.arrayBuffer()
    const uint8Array = new Uint8Array(arrayBuffer)

    // Extract the ZIP contents
    const unzipped = unzipSync(uint8Array)

    // Build markdown document with all files
    let markdown = `# PostHog ${frameworkName.charAt(0).toUpperCase() + frameworkName.slice(1)} Example Project\n\n`
    markdown += `Repository: ${zipUrl.replace('/archive/refs/heads/main.zip', '')}\n\n`
    markdown += '---\n\n'

    // Sort files for consistent output
    const sortedPaths = Object.keys(unzipped).sort()

    for (const filePath of sortedPaths) {
        // Skip directories and non-text files
        if (filePath.endsWith('/')) continue

        // Skip binary files and unwanted files
        if (skipPatterns.some((pattern) => filePath.includes(pattern))) continue

        // Remove the repo folder prefix (e.g., "posthog-app-router-example-main/")
        const cleanPath = filePath.replace(/^[^/]+\//, '')

        try {
            const fileData = unzipped[filePath]
            if (!fileData) continue

            const content = strFromU8(fileData)
            const extension = filePath.split('.').pop() || ''
            const language = getLanguageFromExtension(extension)

            markdown += `## ${cleanPath}\n\n`
            markdown += `\`\`\`${language}\n`
            markdown += content
            markdown += '\n```\n\n'
        } catch (e) {
            // Skip files that can't be decoded as text
        }
    }

    return markdown
}
