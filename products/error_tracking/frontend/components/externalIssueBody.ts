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
    const trace = fitStacktrace(text, stacktrace)
    if (!trace) {
        return text
    }
    const head = text.trimEnd()
    const fence = codeFence(trace)
    return `${head}${head ? '\n\n' : ''}${fence}\n${trace}\n${fence}`
}

/** The part of the stack trace that `appendStacktrace` adds after the text, or an empty string if none fits. */
export function fitStacktrace(text: string, stacktrace: string): string {
    if (!stacktrace) {
        return ''
    }
    const head = text.trimEnd()
    const separator = head ? '\n\n' : ''
    const fence = codeFence(stacktrace)
    const room = MAX_ISSUE_BODY_LENGTH - head.length - separator.length - 2 * (fence.length + 1)
    return truncateAtLineBreak(stacktrace, room)
}

// Source lines in the stack trace can contain backticks, so the fence must be longer than any run of them.
// A trace can have more runs than a function call takes arguments, so the longest run is found without spreading them.
function codeFence(text: string): string {
    const longestBacktickRun = (text.match(/`+/g) ?? []).reduce((longest, run) => Math.max(longest, run.length), 0)
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
