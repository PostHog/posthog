import { describe, expect, it } from 'vitest'

import { getServedSkillFeatureFlags, isSkillServed, parseServedSkills } from '@/skills/served-skills'

describe('served skills', () => {
    const served = parseServedSkills({
        skills: {
            'open-skill': {},
            'gated-skill': { feature_flag: 'gate' },
            'slack-skill': { consumers: ['slack'] },
            'gated-slack-skill': { feature_flag: 'gate', consumers: ['slack'] },
        },
        context_mill_skills: { 'overlay-skill': { feature_flag: 'gate' } },
    })

    it.each([
        { name: 'open-skill', caller: {}, expected: true },
        { name: 'open-skill', caller: { featureFlags: { gate: false }, consumer: 'slack' }, expected: true },
        { name: 'gated-skill', caller: { featureFlags: { gate: true } }, expected: true },
        { name: 'overlay-skill', caller: { featureFlags: { gate: true } }, expected: true },
        { name: 'gated-skill', caller: {}, expected: false },
        { name: 'gated-skill', caller: { featureFlags: { gate: false } }, expected: false },
        { name: 'gated-skill', caller: { featureFlags: { gate: 'some-variant' } }, expected: false },
        { name: 'gated-skill', caller: { featureFlags: { other: true } }, expected: false },
        { name: 'slack-skill', caller: { consumer: 'slack' }, expected: true },
        { name: 'slack-skill', caller: {}, expected: false },
        { name: 'slack-skill', caller: { consumer: 'posthog_ai' }, expected: false },
        { name: 'gated-slack-skill', caller: { featureFlags: { gate: true }, consumer: 'slack' }, expected: true },
        { name: 'gated-slack-skill', caller: { featureFlags: { gate: true } }, expected: false },
        { name: 'gated-slack-skill', caller: { consumer: 'slack' }, expected: false },
        { name: 'unlisted-skill', caller: { featureFlags: { gate: true }, consumer: 'slack' }, expected: false },
        { name: 'constructor', caller: {}, expected: false },
    ])('serves $name to $caller: $expected', ({ name, caller, expected }) => {
        expect(isSkillServed(name, caller, served)).toBe(expected)
    })

    it('collects each flag once for the flag evaluation', () => {
        expect(getServedSkillFeatureFlags(served)).toEqual(['gate'])
    })

    it.each([
        { label: 'a misspelled flag key', entry: { feature_flags: 'gate' } },
        { label: 'an empty flag', entry: { feature_flag: '' } },
        { label: 'a flag that is not a string', entry: { feature_flag: true } },
        { label: 'a consumer the server does not know', entry: { consumers: ['slak'] } },
        { label: 'an empty consumer list', entry: { consumers: [] } },
    ])('rejects $label, so a typo cannot change who gets a skill', ({ entry }) => {
        expect(() => parseServedSkills({ skills: { 'some-skill': entry }, context_mill_skills: {} })).toThrow()
    })
})
