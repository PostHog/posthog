import { describe, expect, it } from 'vitest'

import { getServedSkillFeatureFlags, isSkillServed, parseServedSkills } from '@/skills/served-skills'

describe('served skills', () => {
    const served = parseServedSkills({
        skills: { 'open-skill': {}, 'gated-skill': { feature_flag: 'gate' } },
        context_mill_skills: { 'overlay-skill': { feature_flag: 'gate' } },
    })

    it.each([
        { name: 'open-skill', flags: {}, expected: true },
        { name: 'open-skill', flags: { gate: false }, expected: true },
        { name: 'gated-skill', flags: { gate: true }, expected: true },
        { name: 'overlay-skill', flags: { gate: true }, expected: true },
        { name: 'gated-skill', flags: {}, expected: false },
        { name: 'gated-skill', flags: { gate: false }, expected: false },
        { name: 'gated-skill', flags: { gate: 'some-variant' }, expected: false },
        { name: 'gated-skill', flags: { other: true }, expected: false },
        { name: 'unlisted-skill', flags: { gate: true }, expected: false },
        { name: 'constructor', flags: {}, expected: false },
    ])('serves $name with flags $flags: $expected', ({ name, flags, expected }) => {
        expect(isSkillServed(name, flags, served)).toBe(expected)
    })

    it('collects each flag once for the flag evaluation', () => {
        expect(getServedSkillFeatureFlags(served)).toEqual(['gate'])
    })

    it.each([
        { label: 'a misspelled flag key', entry: { feature_flags: 'gate' } },
        { label: 'an empty flag', entry: { feature_flag: '' } },
        { label: 'a flag that is not a string', entry: { feature_flag: true } },
    ])('rejects $label, so a typo cannot serve a gated skill to everyone', ({ entry }) => {
        expect(() => parseServedSkills({ skills: { 'gated-skill': entry }, context_mill_skills: {} })).toThrow()
    })
})
