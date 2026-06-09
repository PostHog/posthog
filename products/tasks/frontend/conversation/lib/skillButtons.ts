import type { ContentBlock } from '../acp-types'

/**
 * Vendored skill-button id detection from
 * apps/code/src/renderer/features/skill-buttons/prompts.ts.
 *
 * Only `extractSkillButtonId` and the id union are needed by the pipeline;
 * the button metadata table (labels, prompts, icons) is not ported because the
 * read-only transcript never renders the live composer buttons.
 */

export type SkillButtonId =
    | 'add-analytics'
    | 'create-feature-flags'
    | 'run-experiment'
    | 'add-error-tracking'
    | 'instrument-llm-calls'
    | 'add-logging'

const SKILL_BUTTON_IDS: ReadonlySet<string> = new Set<SkillButtonId>([
    'add-analytics',
    'create-feature-flags',
    'run-experiment',
    'add-error-tracking',
    'instrument-llm-calls',
    'add-logging',
])

const SKILL_BUTTON_META_NAMESPACE = 'posthogCode'
const SKILL_BUTTON_META_FIELD = 'skillButtonId'

export function extractSkillButtonId(blocks: ContentBlock[] | undefined): SkillButtonId | null {
    if (!blocks?.length) {
        return null
    }
    for (const block of blocks) {
        const meta = (block as { _meta?: Record<string, unknown> })._meta
        const namespace = meta?.[SKILL_BUTTON_META_NAMESPACE] as Record<string, unknown> | undefined
        const id = namespace?.[SKILL_BUTTON_META_FIELD]
        if (typeof id === 'string' && SKILL_BUTTON_IDS.has(id)) {
            return id as SkillButtonId
        }
    }
    return null
}
