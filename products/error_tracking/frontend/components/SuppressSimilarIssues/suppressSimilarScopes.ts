import { ErrorEventProperties } from 'lib/components/Errors/types'
import { getExceptionTypeAndValue } from 'lib/components/Errors/utils'

import { ErrorTrackingIssue, ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { EventPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

export interface SuppressedIssueSnapshot {
    id: string
    exceptionType: string | null
    exceptionMessage: string | null
}

export type MessageSegmentKind = 'literal' | 'number' | 'id' | 'hex'

export interface MessageSegment {
    kind: MessageSegmentKind
    text: string
}

export interface GeneralizedMessage {
    regex: string
    segments: MessageSegment[]
}

export interface SuppressionEventFilter extends EventPropertyFilter {
    value: string | string[]
}

export interface SuppressionFilterGroup {
    type: FilterLogicalOperator.And
    values: SuppressionEventFilter[]
}

export type SuppressScopeKey = 'exact' | 'similar'

export interface SuppressScopeOption {
    key: SuppressScopeKey
    filters: SuppressionFilterGroup
    messages: MessageSegment[][]
    unavailableReason?: string
}

export interface ScopeImpact {
    exceptions: number
    issueCount: number
}

// The pattern ends up in posthog-js (JS RegExp), cymbal (Rust regex) and HogQL (re2),
// so it only uses syntax all three engines read the same way.
const VARIABLE_PART_REGEX: Record<Exclude<MessageSegmentKind, 'literal'>, string> = {
    id: '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
    hex: '(?:0x)?[0-9a-fA-F]+',
    number: '\\d+(?:\\.\\d+)?',
}

// A number may run into a unit ("3000ms"), so it has no trailing word boundary. The leading one keeps "utf8" intact.
const VARIABLE_PART =
    /(?<id>\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b)|(?<hex>\b0x[0-9a-f]+\b|\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{16,}\b)|(?<number>\b\d+(?:\.\d+)?)/gi

function escapeRegexLiteral(text: string): string {
    return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function distinctNonEmpty(values: (string | null | undefined)[]): string[] {
    return Array.from(new Set(values.filter((value): value is string => !!value && value.trim().length > 0)))
}

function eventFilter(key: string, operator: PropertyOperator, value: string | string[]): SuppressionEventFilter {
    return { key, operator, value, type: PropertyFilterType.Event }
}

function literal(text: string): MessageSegment[] {
    return [{ kind: 'literal', text }]
}

function filterGroup(values: SuppressionEventFilter[]): SuppressionFilterGroup {
    return { type: FilterLogicalOperator.And, values }
}

/** Replaces IDs, hashes and numbers in an exception message with wildcards. Returns null when nothing varies. */
export function generalizeExceptionMessage(message: string): GeneralizedMessage | null {
    const segments: MessageSegment[] = []
    let regex = ''
    let lastIndex = 0

    for (const match of message.matchAll(VARIABLE_PART)) {
        const kind = (Object.keys(VARIABLE_PART_REGEX) as (keyof typeof VARIABLE_PART_REGEX)[]).find(
            (group) => match.groups?.[group] !== undefined
        )
        if (!kind || match.index === undefined) {
            continue
        }
        const text = message.slice(lastIndex, match.index)
        if (text) {
            segments.push({ kind: 'literal', text })
            regex += escapeRegexLiteral(text)
        }
        segments.push({ kind, text: match[0] })
        regex += VARIABLE_PART_REGEX[kind]
        lastIndex = match.index + match[0].length
    }

    if (segments.length === 0) {
        return null
    }

    const tail = message.slice(lastIndex)
    if (tail) {
        segments.push({ kind: 'literal', text: tail })
        regex += escapeRegexLiteral(tail)
    }

    return { regex, segments }
}

export function buildScopeOptions(snapshots: SuppressedIssueSnapshot[]): SuppressScopeOption[] {
    const types = distinctNonEmpty(snapshots.map((snapshot) => snapshot.exceptionType))
    const messages = distinctNonEmpty(snapshots.map((snapshot) => snapshot.exceptionMessage))
    const typeFilters = types.length > 0 ? [eventFilter('$exception_types', PropertyOperator.Exact, types)] : []
    const noMessageReason = snapshots.length === 1 ? 'This issue has no message' : 'These issues have no message'

    const generalized = messages.map(generalizeExceptionMessage)
    // A message with no variable parts still joins the pattern as an escaped literal.
    const patterns = Array.from(
        new Map(
            generalized.map((pattern, index): [string, GeneralizedMessage] => {
                const resolved = pattern ?? {
                    regex: escapeRegexLiteral(messages[index]),
                    segments: literal(messages[index]),
                }
                return [resolved.regex, resolved]
            })
        ).values()
    )
    const patternRegex =
        patterns.length === 1 ? `^${patterns[0].regex}$` : `^(?:${patterns.map((pattern) => pattern.regex).join('|')})$`

    return [
        {
            key: 'exact',
            filters: filterGroup([...typeFilters, eventFilter('$exception_values', PropertyOperator.Exact, messages)]),
            messages: messages.map(literal),
            unavailableReason: messages.length === 0 ? noMessageReason : undefined,
        },
        {
            key: 'similar',
            filters: filterGroup([
                ...typeFilters,
                eventFilter('$exception_values', PropertyOperator.Regex, patternRegex),
            ]),
            messages: patterns.map((pattern) => pattern.segments),
            unavailableReason:
                messages.length === 0
                    ? noMessageReason
                    : generalized.every((pattern) => pattern === null)
                      ? 'Nothing in the message changes between occurrences, such as a number or an ID'
                      : undefined,
        },
    ]
}

export function recommendedScope(options: SuppressScopeOption[]): SuppressScopeKey | null {
    const available = (key: SuppressScopeKey): boolean =>
        options.some((option) => option.key === key && !option.unavailableReason)
    return (['similar', 'exact'] as const).find(available) ?? null
}

export function snapshotFromListIssue(issue: ErrorTrackingIssue): SuppressedIssueSnapshot {
    return {
        id: issue.id,
        exceptionType: issue.name,
        exceptionMessage: issue.description,
    }
}

/** Prefers the event's exception data, because a person can rename an issue and its name then stops matching events. */
export function snapshotFromIssueEvent(
    issue: ErrorTrackingRelationalIssue,
    properties: ErrorEventProperties | null | undefined
): SuppressedIssueSnapshot {
    const { type, value } = properties ? getExceptionTypeAndValue(properties) : { type: undefined, value: undefined }
    return {
        id: issue.id,
        exceptionType: type ?? issue.name,
        exceptionMessage: value ?? issue.description,
    }
}
