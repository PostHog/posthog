import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { MessageTemplate } from 'scenes/max/messages/MessageTemplate'

import { CompatMessage } from '../types'
import { AVAILABLE_TOOLS_ROLE, hasStringContentField, isTextContentItem } from '../utils'

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
            if (typeof part === 'string') {
                parts.push(part)
                continue
            }
            if (isTextContentItem(part)) {
                parts.push(part.text)
            }
        }
        return parts.join('\n')
    }
    if (hasStringContentField(content)) {
        return content.content
    }
    return ''
}

/**
 * Renders a deduplicated turn as a chat-app-style bubble stream — user on the
 * right, everything else (assistant, tool responses, etc.) on the left. Skips
 * `system` and `available tools` pseudo-messages; their context is implicit in
 * the assistant's reply and reachable via the per-turn "Show steps" panel.
 *
 * Deliberately minimal: no headers, no per-message expand toggles, no metadata
 * row, no playground button. The Trace page's `ConversationMessagesDisplay`
 * covers those cases; this surface optimizes for top-to-bottom readability.
 *
 * Messages with empty extractable text (e.g. an assistant message whose only
 * payload is `tool_calls`) are dropped — they'd render as empty bubbles. Tool
 * calls are surfaced through the steps panel until the dedicated tool-call
 * rendering polish lands as its own follow-up.
 */
export function TranscriptBubbleStream({
    inputs,
    outputs,
}: {
    inputs: CompatMessage[]
    outputs: CompatMessage[]
}): JSX.Element | null {
    const visible = [...inputs, ...outputs]
        .filter((m) => !HIDDEN_ROLES.has(m.role))
        .map((m) => ({ message: m, text: extractText(m) }))
        .filter(({ text }) => text.length > 0)

    if (visible.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-1.5">
            {visible.map(({ message, text }, i) => (
                <MessageTemplate key={i} type={message.role === 'user' ? 'human' : 'ai'} wrapperClassName="max-w-[75%]">
                    <LemonMarkdown className="whitespace-pre-wrap break-words">{text}</LemonMarkdown>
                </MessageTemplate>
            ))}
        </div>
    )
}
