import { unescapeXml } from 'lib/components/AgentObjectTags/rewriteAgentObjectTags'

import { stripInjectedBlocks } from 'products/tasks/frontend/spaces/spaceFeedPreview'

const MENTION_TAG =
    /<file\s+path="([^"]+)"\s*\/>|<(github_issue|github_pr)\s+number="([^"]+)"(?:\s+title="([^"]*)")?(?:\s+url="([^"]*)")?\s*\/>|<error_context\s+label="([^"]*)">[\s\S]*?<\/error_context>|<folder\s+path="([^"]+)"\s*\/>|<comment_context\s+label="([^"]*)"(?:\s+screenshot="[^"]*")?>[\s\S]*?<\/comment_context>/g

function lastSegments(path: string, count: number): string {
    return path.split('/').filter(Boolean).slice(-count).join('/') || path
}

function codeSpan(text: string): string {
    return `\`${text.replace(/`/g, "'")}\``
}

function mentionToMarkdown(match: string[]): string {
    const [, file, githubKind, number, title, url, errorLabel, folder, commentLabel] = match
    if (file) {
        return codeSpan(lastSegments(unescapeXml(file), 2))
    }
    if (githubKind) {
        const label = `#${number}${title ? ` - ${unescapeXml(title)}` : ''}`.replace(/[[\]]/g, '')
        return url ? `[${label}](${unescapeXml(url)})` : label
    }
    if (errorLabel) {
        return codeSpan(unescapeXml(errorLabel))
    }
    if (folder) {
        return codeSpan(`${lastSegments(unescapeXml(folder), 1)}/`)
    }
    if (commentLabel !== undefined) {
        return codeSpan(unescapeXml(commentLabel) || 'Comment')
    }
    return match[0]
}

export function userMessageDisplayText(text: string): string {
    return stripInjectedBlocks(text).replace(MENTION_TAG, (...match: string[]) => mentionToMarkdown(match))
}
