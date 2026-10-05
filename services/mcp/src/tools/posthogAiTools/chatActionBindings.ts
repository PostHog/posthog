import type { ScopedCache } from '@/lib/cache/ScopedCache'
import {
    type ChatAction,
    chatActionKey,
    chatActionSlots,
    chatActionTemplate,
    isChatActionSlotValue,
} from '@/tools/chatActions'

export type ChatActionBindingCache = ScopedCache<Record<string, true>>

export class ChatActionBindings {
    constructor(private readonly cache: ChatActionBindingCache | undefined) {}

    async recordResult(toolName: string, actions: ChatAction[], result: unknown): Promise<void> {
        if (!this.cache || result === null || typeof result !== 'object') {
            return
        }
        const cache = this.cache
        const fields = result as Record<string, unknown>
        const keys = actions.flatMap((action) => {
            const values = slotValuesFrom(action, fields)
            return values ? [bindingKey(toolName, action, values)] : []
        })
        await Promise.all(keys.map((key) => cache.set(key, true)))
    }

    async isBound(toolName: string, action: ChatAction, values: ReadonlyMap<string, string>): Promise<boolean> {
        if (slotsOf(action).length === 0) {
            return true
        }
        const key = bindingKey(toolName, action, values)
        try {
            return (await this.cache?.get(key)) === true
        } catch (error) {
            console.warn(`[suggest-actions] could not read the binding ${key}`, error)
            return false
        }
    }
}

function slotsOf(action: ChatAction): string[] {
    return chatActionSlots(chatActionTemplate(action))
}

function slotValuesFrom(action: ChatAction, fields: Record<string, unknown>): Map<string, string> | undefined {
    const slots = slotsOf(action)
    const values = new Map<string, string>()
    for (const slot of slots) {
        const value = fieldAsSlotValue(fields[slot])
        if (value === undefined) {
            return undefined
        }
        values.set(slot, value)
    }
    return values.size > 0 ? values : undefined
}

function fieldAsSlotValue(field: unknown): string | undefined {
    if (typeof field !== 'string' && typeof field !== 'number') {
        return undefined
    }
    const value = String(field)
    return isChatActionSlotValue(value) ? value : undefined
}

function bindingKey(toolName: string, action: ChatAction, values: ReadonlyMap<string, string>): string {
    const args = slotsOf(action).map((slot) => `${slot}=${values.get(slot) ?? ''}`)
    return `chat-action:${chatActionKey(toolName, action.key)}:${args.join('&')}`
}
