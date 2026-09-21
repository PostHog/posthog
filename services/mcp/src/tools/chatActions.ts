import { z } from 'zod'

/**
 * Actions a tool offers after it ran. The PostHog AI chat renders them as buttons under the
 * agent's answer once the agent picks them through `suggest-actions`. Shared by the YAML config
 * schema (declaration time) and the runtime tool-definition schema, so both validate one shape.
 */
export const CHAT_ACTION_KINDS = ['insert', 'send', 'run'] as const
export type ChatActionKind = (typeof CHAT_ACTION_KINDS)[number]

export const ChatActionSchema = z
    .object({
        /** Key local to the offering tool. The agent addresses it as `<tool>.<key>`. */
        key: z.string().regex(/^[a-z0-9-]+$/),
        /** Button label. */
        label: z.string().min(1),
        /** `insert` fills the composer, `send` submits the message, `run` submits a message that names a tool. */
        kind: z.enum(CHAT_ACTION_KINDS),
        /** The tool a `run` action makes the agent call. Required for `run`, forbidden otherwise. */
        tool: z.string().optional(),
        /** Message template with `{slot}` markers the agent fills with `args`. Defaults to the label. */
        message: z.string().optional(),
    })
    .strict()
    .superRefine((action, ctx) => {
        if (action.kind === 'run' && !action.tool) {
            ctx.addIssue({ code: 'custom', message: '`tool` is required for a `run` action', path: ['tool'] })
        }
        if (action.kind !== 'run' && action.tool) {
            ctx.addIssue({ code: 'custom', message: '`tool` is only allowed on a `run` action', path: ['tool'] })
        }
    })

export type ChatAction = z.infer<typeof ChatActionSchema>

const SLOT_RE = /\{([a-zA-Z0-9_]+)\}/g

/** Slot names in declaration order, deduplicated. */
export function chatActionSlots(template: string): string[] {
    return [...new Set([...template.matchAll(SLOT_RE)].map((match) => match[1]!))]
}

/** Fills every `{slot}` in one pass; the substituted values are never scanned for slots. */
export function renderChatActionTemplate(template: string, valueFor: (slot: string) => string): string {
    return template.replace(SLOT_RE, (_match, slot: string) => valueFor(slot))
}

export function chatActionKey(toolName: string, actionKey: string): string {
    return `${toolName}.${actionKey}`
}

/** Splits `<tool>.<key>` at the last dot, since tool names carry no dots and action keys carry none either. */
export function parseChatActionKey(key: string): { toolName: string; actionKey: string } | null {
    const dot = key.lastIndexOf('.')
    if (dot <= 0 || dot === key.length - 1) {
        return null
    }
    return { toolName: key.slice(0, dot), actionKey: key.slice(dot + 1) }
}
