import { formatPrompt } from '@/lib/utils'
import INSTRUCTIONS_TEMPLATE_V1 from '@/templates/instructions-v1.md'
import INSTRUCTIONS_TEMPLATE_V2 from '@/templates/instructions-v2.md'

export const INSTRUCTIONS_V1 = INSTRUCTIONS_TEMPLATE_V1.trim()

export function getInstructions(version?: number, guidelines?: string): string {
    if (version === 2) {
        return formatPrompt(INSTRUCTIONS_TEMPLATE_V2, {
            guidelines: (guidelines ?? '').trim(),
        })
    }
    return INSTRUCTIONS_V1
}
