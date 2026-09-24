import { z } from 'zod'

import type { ChatActionCatalogEntry } from '@/lib/instructions'
import {
    type ChatAction,
    type ChatActionKind,
    chatActionKey,
    chatActionSlots,
    parseChatActionKey,
    renderChatActionTemplate,
} from '@/tools/chatActions'
import { getToolDefinition, getToolDefinitions } from '@/tools/toolDefinitions'
import type { Context, Tool, ToolBase, ZodObjectAny } from '@/tools/types'

export const SUGGEST_ACTIONS_TOOL_NAME = 'suggest-actions'

/** Keeps an agent-supplied value from smuggling line breaks or unbounded text into the composer. */
const MAX_SLOT_VALUE_LENGTH = 200

const schema = z.object({
    actions: z
        .array(
            z.object({
                key: z
                    .string()
                    .describe(
                        'Action key from the "Suggested actions" catalog, as `<tool>.<key>`, e.g. `workflows-create.enable`.'
                    ),
                args: z
                    .record(z.string(), z.union([z.string(), z.number(), z.boolean()]))
                    .optional()
                    .describe('Values for the `{slot}` markers in the action message, keyed by slot name.'),
            })
        )
        .min(1)
        .max(8)
        .describe('The actions to offer, in the order they should appear.'),
})

type SuggestActionsParams = z.infer<typeof schema>

export interface SuggestedAction {
    key: string
    label: string
    kind: ChatActionKind
    /** Final text the click inserts or sends. Templates never reach the client. */
    message: string
}

export interface SuggestActionsResult {
    actions: SuggestedAction[]
    /** Dropped picks, in input order, so the agent can see what did not render. */
    errors: { key: string; reason: string }[]
}

function renderSlotValue(value: string | number | boolean): string {
    const flat = String(value).replace(/\s+/g, ' ').trim()
    // Slice by code point so the cap cannot split a surrogate pair.
    return Array.from(flat).slice(0, MAX_SLOT_VALUE_LENGTH).join('')
}

function resolveAction(
    pick: SuggestActionsParams['actions'][number],
    availableToolNames: ReadonlySet<string> | undefined
): SuggestedAction | { reason: string } {
    const parsed = parseChatActionKey(pick.key)
    // A tool the caller cannot see offers nothing, so its actions read as unknown rather than hint at it.
    if (!parsed || (availableToolNames && !availableToolNames.has(parsed.toolName))) {
        return { reason: 'unknown_action' }
    }
    const action = getToolDefinitions()[parsed.toolName]?.actions?.find((a) => a.key === parsed.actionKey)
    if (!action) {
        return { reason: 'unknown_action' }
    }
    // The catalog is fail-closed: with no bound catalog nothing can vouch for the target.
    if (action.kind === 'run' && !(action.tool && availableToolNames?.has(action.tool))) {
        return { reason: 'run_target_unavailable' }
    }
    const template = action.message ?? action.label
    const values = new Map<string, string>()
    for (const slot of chatActionSlots(template)) {
        const raw = pick.args?.[slot]
        const value = raw === undefined ? '' : renderSlotValue(raw)
        if (!value) {
            return { reason: `missing_slot: ${slot}` }
        }
        values.set(slot, value)
    }
    // One pass over the template, so a value that contains `{other}` is never expanded itself.
    const message = renderChatActionTemplate(template, (slot) => values.get(slot) ?? '')
    return { key: pick.key, label: action.label, kind: action.kind, message }
}

/**
 * Resolves the agent's picks against the declared actions and renders their messages. The
 * PostHog AI chat draws the result as buttons under the answer.
 *
 * `availableToolNames` is the caller's flag- and scope-filtered catalog. Only the request
 * resolver knows it, so `bindSuggestActionsCatalog` swaps in a bound handler per request.
 */
export function createSuggestActionsTool(
    availableToolNames?: ReadonlySet<string>
): ToolBase<typeof schema, SuggestActionsResult> {
    return {
        name: SUGGEST_ACTIONS_TOOL_NAME,
        schema,
        handler: async (_context: Context, params: SuggestActionsParams): Promise<SuggestActionsResult> => {
            const result: SuggestActionsResult = { actions: [], errors: [] }
            for (const pick of params.actions) {
                const resolved = resolveAction(pick, availableToolNames)
                if ('reason' in resolved) {
                    result.errors.push({ key: pick.key, reason: resolved.reason })
                } else {
                    result.actions.push(resolved)
                }
            }
            return result
        },
    }
}

/**
 * The declared actions of the caller's visible tools, only when `suggest-actions` is visible too.
 * A `run` action whose target this caller cannot see is left out, so the agent is never told to
 * offer a click that `suggest-actions` would then refuse. Shared by the command reference and the
 * per-result hint, so both surfaces agree on what the agent may offer.
 */
export function buildChatActionCatalog(visibleToolNames: Iterable<string>): ChatActionCatalogEntry[] | undefined {
    const visible = new Set(visibleToolNames)
    if (!visible.has(SUGGEST_ACTIONS_TOOL_NAME)) {
        return undefined
    }
    return [...visible].flatMap((toolName) => {
        const actions = (getToolDefinition(toolName).actions ?? []).filter(
            (action) => action.kind !== 'run' || (!!action.tool && visible.has(action.tool))
        )
        return actions.length ? [{ tool: toolName, actions }] : []
    })
}

/**
 * The hint appended to a successful result of a tool that declares actions. The command reference
 * lists the same catalog, but tens of thousands of characters away from the result the agent is
 * reading, so the agent tends to miss it there. This puts the exact `suggest-actions` command next
 * to the result it belongs to. Slot values stay placeholders because only the agent knows the values.
 */
export function renderChatActionHint(tool: string, actions: ChatAction[]): string {
    const picks = actions.map((action) => {
        const slots = chatActionSlots(action.message ?? action.label)
        const args = slots.length ? { args: Object.fromEntries(slots.map((slot) => [slot, `<${slot}>`])) } : {}
        return { key: chatActionKey(tool, action.key), ...args }
    })
    return (
        'Suggested actions for this result. If the user is likely to do one of these next, call `suggest-actions` once as the last tool call of this turn and do not list them in prose:\n' +
        `call ${SUGGEST_ACTIONS_TOOL_NAME} ${JSON.stringify({ actions: picks })}`
    )
}

/** Gives the `suggest-actions` entry of a filtered tool list the names of that same list. */
export function bindSuggestActionsCatalog<T extends Tool<ZodObjectAny>>(tools: T[]): T[] {
    if (!tools.some((tool) => tool.name === SUGGEST_ACTIONS_TOOL_NAME)) {
        return tools
    }
    const bound = createSuggestActionsTool(new Set(tools.map((tool) => tool.name)))
    return tools.map((tool) =>
        tool.name === SUGGEST_ACTIONS_TOOL_NAME ? { ...tool, handler: bound.handler as T['handler'] } : tool
    )
}

export default (): ToolBase<typeof schema, SuggestActionsResult> => createSuggestActionsTool()
