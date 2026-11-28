import { type CustomerSurfaceInput, isCustomerFacingSurface } from '@/lib/event-source'
import type { FlagValue } from '@/lib/posthog/flags'

export const INBOX_LIST_TOOL = 'inbox-reports-list'

export type InboxNudgeMode = 'line' | 'line-with-count'

export interface InboxNudgeInput {
    flag: FlagValue
    tools: readonly { name: string }[]
    /** Read only once the flag and the tools allow the line, so a caller needs no client details before that. */
    surface: () => CustomerSurfaceInput
}

function modeOfFlag(flag: FlagValue): InboxNudgeMode | undefined {
    // `true` is the flag without variants. Any other variant, such as an experiment's control, shows nothing.
    if (flag === true || flag === 'line') {
        return 'line'
    }
    return flag === 'line-with-count' ? flag : undefined
}

export function resolveInboxNudgeMode({ flag, tools, surface }: InboxNudgeInput): InboxNudgeMode | undefined {
    const mode = modeOfFlag(flag)
    if (!mode || !tools.some((tool) => tool.name === INBOX_LIST_TOOL) || !isCustomerFacingSurface(surface())) {
        return undefined
    }
    return mode
}
