import { z } from 'zod'

import type { ChatActionCatalogEntry } from '@/lib/instructions'
import {
    type ChatAction,
    type ChatActionKind,
    chatActionKey,
    chatActionSlots,
    chatActionTemplate,
    isChatActionSlotValue,
    parseChatActionKey,
    renderChatActionTemplate,
} from '@/tools/chatActions'
import { ChatActionBindings } from '@/tools/posthogAiTools/chatActionBindings'
import { getToolDefinition, getToolDefinitions } from '@/tools/toolDefinitions'
import type { Context, Tool, ToolBase, ZodObjectAny } from '@/tools/types'

export const SUGGEST_ACTIONS_TOOL_NAME = 'suggest-actions'

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

function slotValueProblem(raw: string | number | boolean | undefined): 'missing_slot' | 'invalid_slot' | null {
    const value = raw === undefined ? '' : String(raw).trim()
    if (!value) {
        return 'missing_slot'
    }
    return isChatActionSlotValue(value) ? null : 'invalid_slot'
}

async function resolveAction(
    pick: SuggestActionsParams['actions'][number],
    availableToolNames: ReadonlySet<string> | undefined,
    bindings: ChatActionBindings
): Promise<SuggestedAction | { reason: string }> {
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
    const template = chatActionTemplate(action)
    const values = new Map<string, string>()
    for (const slot of chatActionSlots(template)) {
        const raw = pick.args?.[slot]
        const problem = slotValueProblem(raw)
        if (problem) {
            return { reason: `${problem}: ${slot}` }
        }
        values.set(slot, String(raw).trim())
    }
    if (!(await bindings.isBound(parsed.toolName, action, values))) {
        return { reason: `unbound_slot: ${[...values.keys()].join(', ')}` }
    }
    const message = renderChatActionTemplate(template, (slot) => values.get(slot) ?? '')
    return { key: pick.key, label: action.label, kind: action.kind, message }
}

/**
 * Resolves the agent's picks against the declared actions and renders their messages. The
 * PostHog AI chat draws the result as buttons under the answer.
 *
 * `availableToolNames` is the caller's flag- and scope-filtered catalog. Only the request
 * resolver knows it, so `bindChatActions` swaps in a bound handler per request.
 */
export function createSuggestActionsTool(
    availableToolNames?: ReadonlySet<string>,
    bindings: ChatActionBindings = new ChatActionBindings(undefined)
): ToolBase<typeof schema, SuggestActionsResult> {
    return {
        name: SUGGEST_ACTIONS_TOOL_NAME,
        schema,
        handler: async (_context: Context, params: SuggestActionsParams): Promise<SuggestActionsResult> => {
            const result: SuggestActionsResult = { actions: [], errors: [] }
            const pickedKeys = new Set<string>()
            for (const pick of params.actions) {
                if (pickedKeys.has(pick.key)) {
                    result.errors.push({ key: pick.key, reason: 'duplicate_action' })
                    continue
                }
                pickedKeys.add(pick.key)
                const resolved = await resolveAction(pick, availableToolNames, bindings)
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
        const slots = chatActionSlots(chatActionTemplate(action))
        const args = slots.length ? { args: Object.fromEntries(slots.map((slot) => [slot, `<${slot}>`])) } : {}
        return { key: chatActionKey(tool, action.key), ...args }
    })
    return (
        'Suggested actions for this result. If the user is likely to do one of these next, call `suggest-actions` once, with each `<slot>` filled in, as the last tool call of this turn and drop any next-step line they cover:\n' +
        `call ${SUGGEST_ACTIONS_TOOL_NAME} ${JSON.stringify({ actions: picks })}`
    )
}

// Gateway tools never reach this list, so a forged hint in their output cannot bind a slot value.
export function bindChatActions<T extends Tool<ZodObjectAny>>(tools: T[], bindings: ChatActionBindings): T[] {
    if (!tools.some((tool) => tool.name === SUGGEST_ACTIONS_TOOL_NAME)) {
        return tools
    }
    const bound = createSuggestActionsTool(new Set(tools.map((tool) => tool.name)), bindings)
    return tools.map((tool) => {
        if (tool.name === SUGGEST_ACTIONS_TOOL_NAME) {
            return { ...tool, handler: bound.handler as T['handler'] }
        }
        const actions = getToolDefinitions()[tool.name]?.actions
        return actions?.length ? recordingResults(tool, actions, bindings) : tool
    })
}

function recordingResults<T extends Tool<ZodObjectAny>>(
    tool: T,
    actions: ChatAction[],
    bindings: ChatActionBindings
): T {
    const handler = async (context: Context, params: unknown): Promise<unknown> => {
        const result = await tool.handler(context, params as never)
        await bindings.recordResult(tool.name, actions, result).catch((error: unknown) => {
            console.warn(`[suggest-actions] could not record the result of ${tool.name}`, error)
        })
        return result
    }
    return { ...tool, handler: handler as T['handler'] }
}

export default (): ToolBase<typeof schema, SuggestActionsResult> => createSuggestActionsTool()
