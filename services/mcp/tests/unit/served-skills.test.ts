import { describe, expect, it } from 'vitest'

import {
    getServedSkillFeatureFlags,
    isSkillServed,
    isSkillServedWithoutFlags,
    parseServedSkills,
    servedSkillsFromHeaders,
} from '@/skills/served-skills'

describe('served skills', () => {
    const served = new Map([
        ...parseServedSkills({
            skills: {
                'open-skill': {},
                'gated-skill': { feature_flag: 'gate' },
                'slack-skill': { consumers: ['slack'] },
                'gated-slack-skill': { feature_flag: 'gate', consumers: ['slack'] },
            },
        }),
        ...servedSkillsFromHeaders([
            { name: 'overlay-skill', audience: 'customer' },
            { name: 'gated-overlay-skill', audience: 'customer', featureFlag: 'gate' },
            { name: 'internal-overlay-skill', audience: 'internal' },
            { name: 'unlabeled-overlay-skill' },
        ]),
    ])

    it.each([
        { name: 'open-skill', caller: {}, expected: true },
        { name: 'open-skill', caller: { featureFlags: { gate: false }, consumer: 'slack' }, expected: true },
        { name: 'gated-skill', caller: { featureFlags: { gate: true } }, expected: true },
        { name: 'overlay-skill', caller: {}, expected: true },
        { name: 'gated-overlay-skill', caller: { featureFlags: { gate: true } }, expected: true },
        { name: 'gated-overlay-skill', caller: {}, expected: false },
        { name: 'internal-overlay-skill', caller: {}, expected: false },
        { name: 'unlabeled-overlay-skill', caller: {}, expected: false },
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
        { label: 'an audience the server does not serve', entry: { audience: 'internal' } },
        { label: 'an empty consumer list', entry: { consumers: [] } },
    ])('rejects $label, so a typo cannot change who gets a skill', ({ entry }) => {
        expect(() => parseServedSkills({ skills: { 'some-skill': entry } })).toThrow()
    })

    it.each([
        { name: 'open-skill', expected: true },
        { name: 'gated-skill', expected: true },
        { name: 'slack-skill', expected: false },
        { name: 'internal-overlay-skill', expected: false },
        { name: 'unlisted-skill', expected: false },
    ])('serves $name to a caller with no flag evaluation: $expected', ({ name, expected }) => {
        expect(isSkillServedWithoutFlags(name, served)).toBe(expected)
    })
})
