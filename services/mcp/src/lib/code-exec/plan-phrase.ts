/**
 * Three-word plan id (`cat-assistant-tree`) referencing a stored plan. The
 * store, not a signature, is the root of trust: the plan-store key embeds the
 * caller's identity, so a phrase is only resolvable by the user who minted it,
 * and 3 words from 1295 ≈ 31 bits against a 10-minute TTL and single-use
 * consumption make in-namespace guessing moot (spec §3.6.4).
 */

import { randomInt } from 'node:crypto'

import { PLAN_PHRASE_WORDS } from './wordlist'

export const PLAN_PHRASE_WORD_COUNT = 3

/** Plan-appropriate TTL: long enough to surface a plan and confirm, short enough to bound replay. */
export const PLAN_PHRASE_TTL_SECONDS = 600

export function generatePlanPhrase(): string {
    return Array.from(
        { length: PLAN_PHRASE_WORD_COUNT },
        () => PLAN_PHRASE_WORDS[randomInt(PLAN_PHRASE_WORDS.length)]
    ).join('-')
}

/**
 * Canonicalize user-supplied plan ids so `apply Cat Assistant Tree` (or an
 * underscore/extra-whitespace variant) resolves to the stored phrase.
 */
export function normalizePlanPhrase(input: string): string {
    return input
        .trim()
        .toLowerCase()
        .replace(/[\s_-]+/g, '-')
        .replace(/^-|-$/g, '')
}
