import { memo, type ReactNode } from 'react'

import { IconFolder, IconWarning } from '@posthog/icons'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { FileMentionChip } from './FileMentionChip'

const MENTION_TAG_REGEX =
    /<file\s+path="([^"]+)"\s*\/>|<(github_issue|github_pr)\s+number="([^"]+)"(?:\s+title="([^"]*)")?(?:\s+url="([^"]*)")?\s*\/>|<error_context\s+label="([^"]*)">[\s\S]*?<\/error_context>|<folder\s+path="([^"]+)"\s*\/>/g
const MENTION_TAG_TEST =
    /<(?:file\s+path|folder\s+path|github_issue\s+number|github_pr\s+number|error_context\s+label)="[^"]+"/
const SLASH_COMMAND_START = /^\/([a-zA-Z][\w-]*)(?=\s|$)/

/** Inline, dependency-free XML attribute unescaping (vendored from utils/xml). */
function unescapeXmlAttr(value: string): string {
    return value
        .replace(/&quot;/g, '"')
        .replace(/&apos;/g, "'")
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&')
}

/**
 * Renders a fragment of inline markdown text between mention tags. Uses
 * `LemonMarkdown` with low-key headings so inline paragraphs stay compact.
 */
export const InlineMarkdown = memo(function InlineMarkdown({ content }: { content: string }): JSX.Element {
    return (
        <LemonMarkdown lowKeyHeadings className="text-[13px]">
            {content}
        </LemonMarkdown>
    )
})

export function hasMentionTags(content: string): boolean {
    return MENTION_TAG_TEST.test(content) || SLASH_COMMAND_START.test(content)
}

export const hasFileMentions = hasMentionTags

/** Generic, non-clickable inline chip (slash commands, folders, error context). */
function GenericMentionChip({ icon, label }: { icon: ReactNode; label: string }): JSX.Element {
    return (
        <span className="mx-0.5 inline-flex min-w-0 max-w-full items-center gap-1 rounded bg-accent-highlight px-1 py-px align-middle text-[13px] font-medium text-accent">
            {icon}
            <span className="truncate">{label}</span>
        </span>
    )
}

/**
 * Parse a content string into text segments and inline mention chips.
 *
 * Mirrors the reference parser: a leading slash command becomes a chip, then
 * `<file>`, `<folder>`, `<error_context>`, and GitHub ref tags are replaced
 * with chips while the surrounding text is rendered as inline markdown.
 * GitHub refs render as plain (non-linked) chips here, since the read-only
 * transcript has no external-link affordance.
 */
export function parseMentionTags(content: string): ReactNode[] {
    const parts: ReactNode[] = []
    let lastIndex = 0

    const slashMatch = content.match(SLASH_COMMAND_START)
    if (slashMatch) {
        parts.push(<GenericMentionChip key="slash-cmd" icon={null} label={`/${slashMatch[1]}`} />)
        lastIndex = slashMatch[0].length
    }

    for (const match of content.matchAll(MENTION_TAG_REGEX)) {
        const matchIndex = match.index ?? 0
        if (matchIndex < lastIndex) {
            continue
        }

        if (matchIndex > lastIndex) {
            parts.push(<InlineMarkdown key={`text-${lastIndex}`} content={content.slice(lastIndex, matchIndex)} />)
        }

        if (match[1]) {
            const filePath = unescapeXmlAttr(match[1])
            const segments = filePath.split('/').filter(Boolean)
            const fileName = segments.pop() ?? filePath
            const parentDir = segments.pop()
            const label = parentDir ? `${parentDir}/${fileName}` : fileName
            parts.push(<FileMentionChip key={`file-${matchIndex}`} path={filePath} label={label} />)
        } else if (match[2]) {
            const issueNumber = match[3]
            const issueTitle = match[4] ? unescapeXmlAttr(match[4]) : undefined
            const label = issueTitle ? `#${issueNumber} - ${issueTitle}` : `#${issueNumber}`
            parts.push(<GenericMentionChip key={`${match[2]}-${matchIndex}`} icon={null} label={label} />)
        } else if (match[6]) {
            parts.push(
                <GenericMentionChip
                    key={`error-ctx-${matchIndex}`}
                    icon={<IconWarning style={{ fontSize: 12 }} />}
                    label={unescapeXmlAttr(match[6])}
                />
            )
        } else if (match[7]) {
            const folderPath = unescapeXmlAttr(match[7])
            const segments = folderPath.split('/').filter(Boolean)
            const folderName = segments.pop() ?? folderPath
            parts.push(
                <GenericMentionChip
                    key={`folder-${matchIndex}`}
                    icon={<IconFolder style={{ fontSize: 12 }} />}
                    label={folderName}
                />
            )
        }

        lastIndex = matchIndex + match[0].length
    }

    if (lastIndex < content.length) {
        parts.push(<InlineMarkdown key={`text-${lastIndex}`} content={content.slice(lastIndex)} />)
    }

    return parts
}

export const parseFileMentions = parseMentionTags

/**
 * Public chip alias. The read-only renderer prefers `FileMentionChip` for file
 * mentions; `MentionChip` is kept as an alias so callers that imported the
 * reference name continue to resolve.
 */
export const MentionChip = FileMentionChip
