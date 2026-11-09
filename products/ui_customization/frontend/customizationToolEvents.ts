import { resolveToolCall } from 'products/posthog_ai/frontend/api/logics'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/api/types'

export const CUSTOMIZATION_WRITE_TOOLS = ['ui-customization-set', 'ui-customization-reset']

export function customizationWasChanged(event: ToolStreamEvent, context: string): boolean {
    if (event.phase !== 'completed' || !CUSTOMIZATION_WRITE_TOOLS.includes(event.toolName)) {
        return false
    }
    const input = resolveToolCall(event.invocation).innerInput ?? event.invocation.input
    return input.context === context
}
