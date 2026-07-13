import { describe, expect, it } from 'vitest'

import { normalizePlanPhrase } from '@/lib/code-exec'
import { PLAN_PHRASE_WORDS } from '@/lib/code-exec/wordlist'

describe('plan phrase', () => {
    // A user retyping the id from chat must still resolve the stored plan.
    it.each([
        ['Cat Assistant Tree'],
        ['cat_assistant_tree'],
        ['  cat-assistant-tree  '],
        ['CAT-ASSISTANT-TREE'],
        ['cat  assistant _ tree'],
    ])('normalizePlanPhrase(%j) canonicalizes to the stored key form', (input) => {
        expect(normalizePlanPhrase(input)).toBe('cat-assistant-tree')
    })

    it('every vendored word is lowercase-alphabetic and unique, so dash-joined phrases parse unambiguously', () => {
        // Guards a re-vendoring that reintroduces "yo-yo" (or dupes), which would
        // corrupt phrase shape and shave entropy.
        expect(PLAN_PHRASE_WORDS.length).toBe(1295)
        expect(new Set(PLAN_PHRASE_WORDS).size).toBe(PLAN_PHRASE_WORDS.length)
        expect(PLAN_PHRASE_WORDS.every((word) => /^[a-z]+$/.test(word))).toBe(true)
    })
})
