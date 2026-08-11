import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import {
    configMatchesScoutTags,
    MAX_SCOUT_TAGS,
    normalizeScoutTag,
    normalizeScoutTags,
    withScoutTagsAdded,
} from './scoutTags'

const config = (tags: string[]): SignalScoutConfigApi =>
    ({
        id: 'config-1',
        tags,
    }) as SignalScoutConfigApi

describe('scoutTags', () => {
    it.each([
        ['Revenue', 'revenue'],
        ['on call', 'on-call'],
        ['cost_spike', 'cost-spike'],
        ['billing/usage', 'billingusage'],
        ['--dashes--', 'dashes'],
        ['a---b', 'a-b'],
    ])('normalizes %s to %s', (input, expected) => {
        expect(normalizeScoutTag(input)).toBe(expected)
    })

    it('normalizes and deduplicates tags before submission', () => {
        expect(normalizeScoutTags(['On Call', 'revenue', 'on_call', ''])).toEqual(['on-call', 'revenue'])
    })

    it('refuses the entire addition when it would exceed the tag limit', () => {
        const existing = Array.from({ length: MAX_SCOUT_TAGS - 1 }, (_, index) => `tag-${index}`)

        expect(withScoutTagsAdded(existing, ['one-more', 'too-many'])).toEqual({ tags: null, overCap: true })
    })

    it('matches any selected tag', () => {
        expect(configMatchesScoutTags(config(['revenue']), ['revenue', 'on-call'])).toBe(true)
        expect(configMatchesScoutTags(config(['security']), ['revenue', 'on-call'])).toBe(false)
    })
})
