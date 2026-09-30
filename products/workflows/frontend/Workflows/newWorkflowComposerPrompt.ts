import { combineUrl } from 'kea-router'

import { AI_COMPOSER_MODE_VALUE, EDITOR_MODE_PARAM, HANDOFF_SOURCE_PARAM } from 'scenes/max/aiFirstCreate/aiFirstMode'
import { urls } from 'scenes/urls'

// pinned: URL search param. Another surface hands a described workflow to the composer with it.
export const COMPOSER_PROMPT_PARAM = 'prompt'

// The prompt is URL-controlled, so it is capped before it reaches the composer.
export const MAX_COMPOSER_PROMPT_LENGTH = 2000

function normalizeComposerPrompt(raw: unknown): string | null {
    // kea-router parses a numeric-looking param into a number, and a number is still a prompt someone typed.
    const text = typeof raw === 'string' ? raw : typeof raw === 'number' ? String(raw) : ''
    const prompt = text.trim().slice(0, MAX_COMPOSER_PROMPT_LENGTH)
    return prompt || null
}

/** The prompt carried by the URL, or null when it is absent, empty, or not text. */
export function readComposerPrompt(searchParams: Record<string, any>): string | null {
    return normalizeComposerPrompt(searchParams[COMPOSER_PROMPT_PARAM])
}

/**
 * The composer URL for a workflow someone already described elsewhere. `source` names that surface for
 * analytics and lets the composer open for the handoff (see `newWorkflowLogic.aiComposerAvailable`).
 */
export function urlForNewWorkflowComposerWithPrompt(prompt: string, source: string): string {
    return combineUrl(urls.workflowNew(), {
        [EDITOR_MODE_PARAM]: AI_COMPOSER_MODE_VALUE,
        [COMPOSER_PROMPT_PARAM]: normalizeComposerPrompt(prompt) ?? undefined,
        [HANDOFF_SOURCE_PARAM]: source,
    }).url
}
