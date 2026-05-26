import posthog from 'posthog-js'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { MessageTemplate } from 'scenes/max/messages/MessageTemplate'

import { CompatMessage } from '../types'
import {
    AVAILABLE_TOOLS_ROLE,
    extractTextContent,
    getScaffoldTagName,
    hasStringContentField,
    isToolStepItem,
} from '../utils'

// Roles that carry no user-visible content in a chat-app view. System prompts
// and the synthetic "available tools" message are noise here; their effects are
// visible through the assistant's behavior, and the full message tree is still
// one click away via "Show steps".
const HIDDEN_ROLES = new Set<string>(['system', AVAILABLE_TOOLS_ROLE])

function extractText(message: CompatMessage): string {
    const content = message.content
    if (typeof content === 'string') {
        return content
    }
    if (Array.isArray(content)) {
        const parts: string[] = []
        for (const part of content) {
            const text = extractTextContent(part)
            if (text !== undefined) {
                parts.push(text)
            }
        }
        return parts.join('\n')
    }
    if (hasStringContentField(content)) {
        return content.content
    }
    return ''
}

function isUnrenderableContentItem(item: unknown): boolean {
    return extractTextContent(item) === undefined && !isToolStepItem(item)
}

export function hasNonTextContent(message: CompatMessage): boolean {
    const content = message.content
    if (!Array.isArray(content)) {
        return false
    }
    return content.some(isUnrenderableContentItem)
}

// Item kinds for the analytics capture, so we can pivot by what we failed to render.
export function unrenderableContentKinds(message: CompatMessage): string[] {
    const content = message.content
    if (!Array.isArray(content)) {
        return []
    }
    const kinds = content
        .filter(isUnrenderableContentItem)
        .map((item) => (typeof item === 'object' && item !== null && 'type' in item ? String(item.type) : typeof item))
    return Array.from(new Set(kinds)).sort()
}

// Content-hash so the analytics capture dedups across kea selector recomputes
// (a sibling turn's `loadFullTrace` invalidates every turn's `newInputs` reference).
function unrenderableKey(message: CompatMessage): string {
    let serialized: string
    try {
        serialized = JSON.stringify(message.content)
    } catch {
        serialized = String(message.content)
    }
    return `${message.role}::${serialized}`
}

export function captureUnrenderableMessageOnce(message: CompatMessage, seen: Set<string>): void {
    const key = unrenderableKey(message)
    if (seen.has(key)) {
        return
    }
    seen.add(key)
    posthog.capture('llma transcript message unrenderable', {
        role: message.role,
        content_kinds: unrenderableContentKinds(message),
    })
}

// An item in the rendered transcript stream. Bubbles render as `MessageTemplate`s.
// Scaffold groups render as a single collapsed pill where the hidden messages
// would have sat — preserving chronological position without polluting the chat.
type StreamItem =
    | { kind: 'bubble'; message: CompatMessage; text: string; nonText: boolean }
    | { kind: 'scaffold-group'; messages: CompatMessage[]; tagNames: string[]; role: string }

interface ClassifiedMessage {
    kind: 'bubble' | 'scaffold'
    message: CompatMessage
    text: string
    nonText: boolean
    scaffoldTag: string | undefined
}

function classifyMessages(messages: CompatMessage[]): ClassifiedMessage[] {
    const result: ClassifiedMessage[] = []
    for (const message of messages) {
        if (HIDDEN_ROLES.has(message.role)) {
            continue
        }
        const scaffoldTag = getScaffoldTagName(message)
        if (scaffoldTag !== undefined) {
            result.push({ kind: 'scaffold', message, text: '', nonText: false, scaffoldTag })
            continue
        }
        const text = extractText(message)
        const nonText = hasNonTextContent(message)
        if (text.length === 0 && !nonText) {
            continue
        }
        result.push({ kind: 'bubble', message, text, nonText, scaffoldTag: undefined })
    }
    return result
}

function groupScaffolds(classified: ClassifiedMessage[]): StreamItem[] {
    const result: StreamItem[] = []
    let pendingScaffolds: ClassifiedMessage[] = []
    const makeGroup = (): void => {
        if (pendingScaffolds.length === 0) {
            return
        }
        result.push({
            kind: 'scaffold-group',
            messages: pendingScaffolds.map((b) => b.message),
            tagNames: pendingScaffolds.map((b) => b.scaffoldTag!),
            // All pending scaffolds share the same role (the predicate only
            // accepts `role: 'user'`), so picking the first is sufficient and
            // future-proof if we relax the predicate later.
            role: pendingScaffolds[0].message.role,
        })
        pendingScaffolds = []
    }
    for (const item of classified) {
        if (item.kind === 'scaffold') {
            pendingScaffolds.push(item)
            continue
        }
        makeGroup()
        result.push({ kind: 'bubble', message: item.message, text: item.text, nonText: item.nonText })
    }
    makeGroup()
    return result
}

// Exported so the test can pin the grouping logic without rendering React.
export function buildStreamItems(messages: CompatMessage[]): StreamItem[] {
    return groupScaffolds(classifyMessages(messages))
}

/**
 * Renders a deduplicated turn as a chat-app-style bubble stream — user on the
 * right, everything else (assistant, tool responses, etc.) on the left. Skips
 * `system` and `available tools` pseudo-messages; their context is implicit in
 * the assistant's reply and reachable via the per-turn "Show steps" panel.
 * Framework prompt-scaffold messages (e.g. `<system_reminder>...`) are collapsed.
 *
 * Deliberately minimal otherwise: no headers, no per-message expand toggles, no
 * metadata row, no playground button. The Trace page's `ConversationMessagesDisplay`
 * covers those cases; this surface optimizes for top-to-bottom readability.
 */
export function TranscriptBubbleStream({
    inputs,
    outputs,
}: {
    inputs: CompatMessage[]
    outputs: CompatMessage[]
}): JSX.Element | null {
    const items = useMemo(() => buildStreamItems([...inputs, ...outputs]), [inputs, outputs])

    const capturedRef = useRef<Set<string>>(new Set())
    useEffect(() => {
        for (const item of items) {
            if (item.kind === 'bubble' && item.nonText) {
                captureUnrenderableMessageOnce(item.message, capturedRef.current)
            }
        }
    }, [items])

    if (items.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-1.5">
            {items.map((item, i) =>
                item.kind === 'bubble' ? (
                    <MessageTemplate
                        key={i}
                        type={item.message.role === 'user' ? 'human' : 'ai'}
                        wrapperClassName="max-w-[75%]"
                    >
                        {item.text && (
                            <LemonMarkdown className="whitespace-pre-wrap break-words">{item.text}</LemonMarkdown>
                        )}
                        {item.nonText && <div className="italic text-muted text-xs mt-1">(has attachments)</div>}
                    </MessageTemplate>
                ) : (
                    <ScaffoldGroupPill key={i} messages={item.messages} tagNames={item.tagNames} role={item.role} />
                )
            )}
        </div>
    )
}

function ScaffoldGroupPill({
    messages,
    tagNames,
    role,
}: {
    messages: CompatMessage[]
    tagNames: string[]
    role: string
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const distinctTags = useMemo(() => Array.from(new Set(tagNames)), [tagNames])
    const count = messages.length
    const label = count === 1 ? '1 hidden context block' : `${count} hidden context blocks`
    // Mirror the bubble-alignment convention: user-role on the right, everything else on the left.
    const alignSelf = role === 'user' ? 'self-end' : 'self-start'
    return (
        <div className={`flex flex-col gap-1 text-xs text-muted max-w-[75%] ${alignSelf}`}>
            <button
                type="button"
                className="flex items-center gap-1 hover:text-default text-left cursor-pointer"
                onClick={() => setExpanded((v) => !v)}
            >
                <IconChevronRight className={`transition-transform ${expanded ? 'rotate-90' : ''}`} />
                <span>{expanded ? `Hide ${label}` : `Show ${label}`}</span>
                {!expanded && distinctTags.length > 0 && (
                    <span className="font-mono opacity-60">— {distinctTags.join(', ')}</span>
                )}
            </button>
            {expanded && (
                <div className="flex flex-col gap-1.5 opacity-70">
                    {messages.map((m, i) => (
                        <pre
                            key={i}
                            className="font-mono whitespace-pre-wrap break-words text-xs m-0 px-2 py-1 bg-bg-light rounded border"
                        >
                            {extractText(m)}
                        </pre>
                    ))}
                </div>
            )}
        </div>
    )
}
