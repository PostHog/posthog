import { isStoredCrashFirst } from 'lib/components/Errors/displayOrder'
import { ErrorEventType } from 'lib/components/Errors/types'
import { getExceptionList } from 'lib/components/Errors/utils'

import { generateStacktraceText } from '../hooks/use-stacktrace-display'

// Jira rejects a description over 32,767 characters. That is the lowest limit of the four providers, so every body stays under it.
export const MAX_ISSUE_BODY_LENGTH = 32767

const TRUNCATION_MARKER = '\n...'

export function getStacktrace(event: ErrorEventType | null, stackFrameRecords: Record<string, any>): string {
    if (!event) {
        return ''
    }
    return generateStacktraceText(getExceptionList(event.properties), stackFrameRecords, {
        includeInAppMarkers: false,
        storedCrashFirst: isStoredCrashFirst(event.properties?.$lib, event.timestamp),
    })
}

/** Adds the stack trace as a Markdown code block after the text, cut at a line break if the body would be too long. */
export function appendStacktrace(text: string, stacktrace: string): string {
    if (!stacktrace) {
        return text
    }
    const head = text.trimEnd()
    const separator = head ? '\n\n' : ''
    const fence = codeFence(stacktrace)
    const room = MAX_ISSUE_BODY_LENGTH - head.length - separator.length - 2 * (fence.length + 1)
    const trace = truncateAtLineBreak(stacktrace, room)
    if (!trace) {
        return text
    }
    return `${head}${separator}${fence}\n${trace}\n${fence}`
}

// Source lines in the stack trace can contain backticks, so the fence must be longer than any run of them.
function codeFence(text: string): string {
    const longestBacktickRun = Math.max(0, ...(text.match(/`+/g) ?? []).map((run) => run.length))
    return '`'.repeat(Math.max(3, longestBacktickRun + 1))
}

function truncateAtLineBreak(text: string, maxLength: number): string {
    if (text.length <= maxLength) {
        return text
    }
    const limit = maxLength - TRUNCATION_MARKER.length
    if (limit <= 0) {
        return ''
    }
    const lastLineBreak = text.lastIndexOf('\n', limit)
    return `${text.slice(0, lastLineBreak > 0 ? lastLineBreak : limit)}${TRUNCATION_MARKER}`
}
