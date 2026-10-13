import { unescapeXml } from 'lib/components/AgentObjectTags/rewriteAgentObjectTags'

export const COMMENT_CONTEXT_TAG = 'comment_context'

export interface CommentContext {
    label: string
    body: string
}

export type MessageSegment = { type: 'text'; text: string } | ({ type: 'comment_context' } & CommentContext)

const COMMENT_CONTEXT_BLOCK = /<comment_context\b([^>]*)>([\s\S]*?)<\/comment_context>/g
const LABEL_ATTR = /\blabel="([^"]*)"/
const FILE_TAG = /<file\s+path="[^"]*"\s*\/>\n?/g

function escapeXmlText(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function escapeXmlAttr(value: string): string {
    return escapeXmlText(value).replace(/"/g, '&quot;')
}

export function commentContextXml({ label, body }: CommentContext): string {
    return `<${COMMENT_CONTEXT_TAG} label="${escapeXmlAttr(label)}">\n${escapeXmlText(body)}\n</${COMMENT_CONTEXT_TAG}>`
}

export function withCommentContexts(contexts: CommentContext[], content: string): string {
    if (contexts.length === 0) {
        return content
    }
    return [...contexts.map(commentContextXml), content].join('\n')
}

export function splitCommentContexts(text: string): MessageSegment[] {
    const segments: MessageSegment[] = []
    let cursor = 0
    for (const match of text.matchAll(COMMENT_CONTEXT_BLOCK)) {
        const before = text.slice(cursor, match.index)
        if (before.trim()) {
            segments.push({ type: 'text', text: before })
        }
        const label = unescapeXml(LABEL_ATTR.exec(match[1])?.[1] ?? '') || 'Comment'
        const body = unescapeXml(match[2].replace(FILE_TAG, '').trim())
        segments.push({ type: 'comment_context', label, body })
        cursor = match.index + match[0].length
    }
    const rest = text.slice(cursor)
    if (rest.trim() || segments.length === 0) {
        segments.push({ type: 'text', text: rest })
    }
    return segments
}
