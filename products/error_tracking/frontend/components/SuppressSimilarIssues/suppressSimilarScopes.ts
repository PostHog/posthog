import {
    EventPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyGroupFilterValue,
    PropertyOperator,
} from '~/types'

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
    // One rule per exception type. A single rule would also match one issue's type with another issue's message.
    rules: SuppressionFilterGroup[]
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
    hex: '(?:0[xX])?[0-9a-fA-F]+',
    // Not `\d`, because the Rust regex crate in cymbal reads it as any Unicode digit.
    number: '[0-9]+(?:\\.[0-9]+)?',
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

function messagePatterns(messages: string[]): GeneralizedMessage[] {
    // A message with no variable parts still joins the pattern as an escaped literal.
    return Array.from(
        new Map(
            messages.map((message): [string, GeneralizedMessage] => {
                const resolved = generalizeExceptionMessage(message) ?? {
                    regex: escapeRegexLiteral(message),
                    segments: literal(message),
                }
                return [resolved.regex, resolved]
            })
        ).values()
    )
}

function anchoredAlternation(patterns: GeneralizedMessage[]): string {
    return patterns.length === 1
        ? `^${patterns[0].regex}$`
        : `^(?:${patterns.map((pattern) => pattern.regex).join('|')})$`
}

export function buildScopeOptions(snapshots: SuppressedIssueSnapshot[]): SuppressScopeOption[] {
    const messagesByType = new Map<string | null, string[]>()
    for (const snapshot of snapshots) {
        const message = snapshot.exceptionMessage?.trim() ? snapshot.exceptionMessage : null
        if (message) {
            const type = snapshot.exceptionType?.trim() ? snapshot.exceptionType : null
            messagesByType.set(type, distinctNonEmpty([...(messagesByType.get(type) ?? []), message]))
        }
    }
    const groups = Array.from(messagesByType.entries())
    const typeFilters = (type: string | null): SuppressionEventFilter[] =>
        type ? [eventFilter('$exception_types', PropertyOperator.Exact, [type])] : []
    const messages = distinctNonEmpty(groups.flatMap(([, groupMessages]) => groupMessages))
    const noMessageReason = snapshots.length === 1 ? 'This issue has no message' : 'These issues have no message'

    return [
        {
            key: 'exact',
            rules: groups.map(([type, groupMessages]) =>
                filterGroup([
                    ...typeFilters(type),
                    eventFilter('$exception_values', PropertyOperator.Exact, groupMessages),
                ])
            ),
            messages: messages.map(literal),
            unavailableReason: messages.length === 0 ? noMessageReason : undefined,
        },
        {
            key: 'similar',
            rules: groups.map(([type, groupMessages]) =>
                filterGroup([
                    ...typeFilters(type),
                    eventFilter(
                        '$exception_values',
                        PropertyOperator.Regex,
                        anchoredAlternation(messagePatterns(groupMessages))
                    ),
                ])
            ),
            messages: messagePatterns(messages).map((pattern) => pattern.segments),
            unavailableReason:
                messages.length === 0
                    ? noMessageReason
                    : messages.every((message) => generalizeExceptionMessage(message) === null)
                      ? 'Nothing in the message changes between occurrences, such as a number or an ID'
                      : undefined,
        },
    ]
}

export function combinedFilter(option: SuppressScopeOption): PropertyGroupFilterValue {
    return option.rules.length === 1 ? option.rules[0] : { type: FilterLogicalOperator.Or, values: option.rules }
}

export function recommendedScope(options: SuppressScopeOption[]): SuppressScopeKey | null {
    const available = (key: SuppressScopeKey): boolean =>
        options.some((option) => option.key === key && !option.unavailableReason)
    return (['similar', 'exact'] as const).find(available) ?? null
}

/** One exception property as HogQL returns it: a JSON array in a string. Takes the outermost exception. */
function firstValue(raw: unknown): string | null {
    if (typeof raw !== 'string' || !raw) {
        return null
    }
    try {
        const parsed: unknown = JSON.parse(raw)
        const first = Array.isArray(parsed) ? parsed[0] : parsed
        return typeof first === 'string' ? first : null
    } catch {
        return raw
    }
}

export function snapshotFromLatestEvent([id, types, values]: [string, unknown, unknown]): SuppressedIssueSnapshot {
    return { id: String(id), exceptionType: firstValue(types), exceptionMessage: firstValue(values) }
}
