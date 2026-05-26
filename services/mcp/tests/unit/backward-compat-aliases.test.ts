import { describe, expect, it } from 'vitest'

import { applyBackwardCompatParamAliases, TOOL_PARAM_ALIASES } from '@/lib/backward-compat-aliases'

describe('applyBackwardCompatParamAliases', () => {
    it('rewrites skill_identifier to skill_name on llma-skill-get', () => {
        const out = applyBackwardCompatParamAliases('llma-skill-get', { skill_identifier: 'skills-store' })
        expect(out).toEqual({ skill_name: 'skills-store' })
    })

    it('rewrites skill_identifier to skill_name on llma-skill-update', () => {
        const out = applyBackwardCompatParamAliases('llma-skill-update', {
            skill_identifier: 'skills-store',
            base_version: 1,
            body: '# Updated',
        })
        expect(out).toEqual({ skill_name: 'skills-store', base_version: 1, body: '# Updated' })
    })

    it('leaves params untouched when canonical key is already set', () => {
        const out = applyBackwardCompatParamAliases('llma-skill-get', {
            skill_name: 'real-name',
            skill_identifier: 'ignored',
        })
        // The alias is only rewritten when the canonical key is absent —
        // the explicit skill_name wins, and skill_identifier is left alone
        // so the schema's "no unknown keys" check still rejects it.
        expect(out).toEqual({ skill_name: 'real-name', skill_identifier: 'ignored' })
    })

    it('leaves params untouched for tools without alias entries', () => {
        const params = { skill_identifier: 'foo' }
        const out = applyBackwardCompatParamAliases('some-other-tool', params)
        expect(out).toBe(params)
    })

    it('returns input as-is when params is undefined or not an object', () => {
        expect(applyBackwardCompatParamAliases('llma-skill-get', undefined as unknown)).toBeUndefined()
        expect(applyBackwardCompatParamAliases('llma-skill-get', 'string' as unknown)).toBe('string')
        expect(applyBackwardCompatParamAliases('llma-skill-get', null as unknown)).toBeNull()
    })

    it('does not mutate the original params object', () => {
        const params = { skill_identifier: 'skills-store' }
        applyBackwardCompatParamAliases('llma-skill-get', params)
        expect(params).toEqual({ skill_identifier: 'skills-store' })
    })

    it('covers both affected tools', () => {
        // Tripwire: if either entry is removed, update or remove this test
        // and the sunset comment on the entry.
        expect(Object.keys(TOOL_PARAM_ALIASES)).toEqual(
            expect.arrayContaining(['llma-skill-get', 'llma-skill-update'])
        )
    })
})
