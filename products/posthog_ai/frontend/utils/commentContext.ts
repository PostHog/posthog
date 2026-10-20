import { unescapeXml } from 'lib/components/AgentObjectTags/rewriteAgentObjectTags'

export const COMMENT_CONTEXT_TAG = 'comment_context'

export interface CommentContext {
    label: string
    body: string
    screenshot?: string
}

export type MessageSegment = { type: 'text'; text: string } | ({ type: 'comment_context' } & CommentContext)

const OPEN_TAG = `<${COMMENT_CONTEXT_TAG}`
const CLOSE_TAG = `</${COMMENT_CONTEXT_TAG}>`
const LABEL_ATTR = /\blabel="([^"]*)"/
const SCREENSHOT_ATTR = /\bscreenshot="([^"]*)"/
const FILE_TAG = /<file\s+path="[^"]*"\s*\/>\n?/g

function escapeXmlText(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function escapeXmlAttr(value: string): string {
    return escapeXmlText(value).replace(/"/g, '&quot;')
}

export function commentContextXml({ label, body, screenshot }: CommentContext): string {
    const screenshotAttr = screenshot ? ` screenshot="${escapeXmlAttr(screenshot)}"` : ''
    return `<${COMMENT_CONTEXT_TAG} label="${escapeXmlAttr(label)}"${screenshotAttr}>\n${escapeXmlText(body)}\n</${COMMENT_CONTEXT_TAG}>`
}

export function withCommentContexts(contexts: CommentContext[], content: string): string {
    if (contexts.length === 0) {
        return content
    }
    return [...contexts.map(commentContextXml), content].join('\n')
}

function commentContextOf({ label, body, screenshot }: CommentContext): CommentContext {
    return screenshot ? { label, body, screenshot } : { label, body }
}

interface CommentContextBlock extends CommentContext {
    start: number
    end: number
}

function findCommentContextBlocks(text: string): CommentContextBlock[] {
    const blocks: CommentContextBlock[] = []
    let cursor = 0
    while (cursor < text.length) {
        const start = text.indexOf(OPEN_TAG, cursor)
        if (start === -1) {
            break
        }
        const afterName = text[start + OPEN_TAG.length]
        if (afterName !== '>' && !/\s/.test(afterName ?? '')) {
            cursor = start + OPEN_TAG.length
            continue
        }
        const openEnd = text.indexOf('>', start)
        if (openEnd === -1) {
            break
        }
        const close = text.indexOf(CLOSE_TAG, openEnd)
        if (close === -1) {
            break
        }
        const attrs = text.slice(start + OPEN_TAG.length, openEnd)
        const screenshot = SCREENSHOT_ATTR.exec(attrs)?.[1]
        blocks.push({
            ...(screenshot ? { screenshot: unescapeXml(screenshot) } : {}),
            start,
            end: close + CLOSE_TAG.length,
            label: unescapeXml(LABEL_ATTR.exec(attrs)?.[1] ?? '') || 'Comment',
            body: unescapeXml(
                text
                    .slice(openEnd + 1, close)
                    .replace(FILE_TAG, '')
                    .trim()
            ),
        })
        cursor = close + CLOSE_TAG.length
    }
    return blocks
}

export function splitCommentContexts(text: string): MessageSegment[] {
    const segments: MessageSegment[] = []
    let cursor = 0
    for (const { start, end, ...context } of findCommentContextBlocks(text)) {
        const before = text.slice(cursor, start)
        if (before.trim()) {
            segments.push({ type: 'text', text: before })
        }
        segments.push({ type: 'comment_context', ...context })
        cursor = end
    }
    const rest = text.slice(cursor)
    if (rest.trim() || segments.length === 0) {
        segments.push({ type: 'text', text: rest })
    }
    return segments
}

export function extractCommentContexts(text: string): { contexts: CommentContext[]; text: string } {
    const segments = splitCommentContexts(text)
    return {
        contexts: segments.flatMap((segment) =>
            segment.type === 'comment_context' ? [commentContextOf(segment)] : []
        ),
        text: segments
            .flatMap((segment) => (segment.type === 'text' ? [segment.text.trim()] : []))
            .filter(Boolean)
            .join('\n\n'),
    }
}

export function splitLeadingCommentContexts(text: string): {
    prefix: string
    contexts: CommentContext[]
    text: string
} {
    const contexts: CommentContext[] = []
    let prefixEnd = 0
    for (const block of findCommentContextBlocks(text)) {
        if (text.slice(prefixEnd, block.start).trim()) {
            break
        }
        contexts.push(commentContextOf(block))
        prefixEnd = block.end
    }
    const rest = text.slice(prefixEnd)
    const textStart = prefixEnd + (rest.length - rest.trimStart().length)
    return { prefix: text.slice(0, textStart), contexts, text: text.slice(textStart) }
}

export function commentContextPreview({ label, body }: CommentContext): string {
    const quoteLines: string[] = []
    const snippetLines: string[] = []
    let fence: string | null = null
    for (const line of body.split('\n')) {
        const opening: string | undefined = fence === null ? line.match(/^`{3,}/)?.[0] : undefined
        if (opening) {
            fence = opening
        } else if (fence !== null && line === fence) {
            fence = null
        } else if (fence !== null) {
            snippetLines.push(line)
        } else if (line.startsWith('> ') || line === '>') {
            quoteLines.push(line.slice(2))
        }
    }
    return quoteLines.length > 0 ? quoteLines.join('\n') : snippetLines.length > 0 ? snippetLines.join('\n') : label
}

export function commentScreenshotNames(text: string): Set<string> {
    return new Set(findCommentContextBlocks(text).flatMap((block) => (block.screenshot ? [block.screenshot] : [])))
}
